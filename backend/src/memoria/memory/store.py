"""Memory store adapter: one memory store per tenant, plus a JSON registry of provisioned ids."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import anthropic

SNAPSHOT_CONCURRENCY = 8
LIST_PAGE_SIZE = 100


class JsonRegistry:
    """Ids of provisioned remote resources, persisted so restarts reuse them.

    Writes go through a temp file and an atomic rename, so a crash never leaves
    a half-written registry. `update` re-reads before writing so independent
    components sharing one file do not overwrite each other's keys.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text())
        except json.JSONDecodeError as exc:
            raise ValueError(f"registry {self.path} is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"registry {self.path} must hold a JSON object")
        return data

    def update(self, mutate: Callable[[dict[str, Any]], None]) -> None:
        data = self.read()
        mutate(data)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as tmp:
                json.dump(data, tmp, indent=2, sort_keys=True)
            os.replace(tmp_name, self.path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise


class ManagedMemoryStore:
    """Implements ports.MemoryStore on the Managed Agents memory store API."""

    def __init__(self, client: anthropic.AsyncAnthropic, registry_path: Path) -> None:
        self._client = client
        self._registry = JsonRegistry(registry_path)
        self._create_lock = asyncio.Lock()

    async def ensure_store(self, tenant_id: str, tenant_name: str) -> str:
        # The lock covers check and create so concurrent callers cannot make two stores for one tenant.
        async with self._create_lock:
            existing = self._registry.read().get("memory_stores", {}).get(tenant_id)
            if existing:
                return existing
            created = await self._client.beta.memory_stores.create(
                name=f"Memoria: {tenant_name}",
                description=(
                    f"Long-term sales memory for one tenant, {tenant_name}: accounts, "
                    "objections, competitive intel, strategy and what worked. Never shared "
                    "with another tenant."
                ),
                metadata={"tenant_id": tenant_id, "app": "memoria"},
            )
            self._registry.update(
                lambda data: data.setdefault("memory_stores", {}).__setitem__(tenant_id, created.id)
            )
            return created.id

    async def snapshot(self, memory_store_id: str, path_prefix: str = "/") -> dict[str, str]:
        # The list endpoint's order is unspecified, so the result is sorted client-side.
        files = [
            item
            async for item in self._client.beta.memory_stores.memories.list(
                memory_store_id, path_prefix=path_prefix, limit=LIST_PAGE_SIZE
            )
            if item.type == "memory"
        ]
        gate = asyncio.Semaphore(SNAPSHOT_CONCURRENCY)

        async def read(item: Any) -> tuple[str, str]:
            async with gate:
                full = await self._client.beta.memory_stores.memories.retrieve(
                    item.id, memory_store_id=memory_store_id
                )
            return item.path, full.content or ""

        pairs = await asyncio.gather(*(read(item) for item in files))
        return dict(sorted(pairs))
