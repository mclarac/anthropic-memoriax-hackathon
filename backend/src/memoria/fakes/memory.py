"""In-memory MemoryStore and AgentRuntime for tests and MEMORIA_MODE=fake.

Behavior follows docs/contract.md "Fake mode behavior": the memory writer
adds or modifies the account's objections and strategy files, so a second
session produces `modified` diffs, and the briefer leads with "Since our last
session:" once two sessions are remembered.
"""

from __future__ import annotations

import re
from typing import Literal

from memoria.ports import AgentRunResult

ACCOUNT_LINE = re.compile(r"^Account:\s*([a-z0-9][a-z0-9-]*)\s*$", re.MULTILINE)
SESSION_LINE = re.compile(r"^Session \d+:", re.MULTILINE)


class FakeMemoryStore:
    """Implements ports.MemoryStore with one dict per store id."""

    def __init__(self) -> None:
        self._stores: dict[str, dict[str, str]] = {}

    async def ensure_store(self, tenant_id: str, tenant_name: str) -> str:
        store_id = f"fake-store-{tenant_id}"
        self._stores.setdefault(store_id, {})
        return store_id

    async def snapshot(self, memory_store_id: str, path_prefix: str = "/") -> dict[str, str]:
        files = self._stores.get(memory_store_id, {})
        return {p: files[p] for p in sorted(files) if p.startswith(path_prefix)}

    def write(self, memory_store_id: str, path: str, content: str) -> None:
        # Unknown ids are created on demand: tenants persisted to disk outlive this in-process store.
        self._stores.setdefault(memory_store_id, {})[path] = content


class FakeAgentRuntime:
    """Implements ports.AgentRuntime on top of a FakeMemoryStore."""

    def __init__(self, memory: FakeMemoryStore) -> None:
        self._memory = memory

    async def run(
        self,
        *,
        role: Literal["memory_writer", "briefer"],
        memory_store_id: str,
        access: Literal["read_write", "read_only"],
        user: str,
        title: str,
    ) -> AgentRunResult:
        match = ACCOUNT_LINE.search(user)
        if match is None:
            raise ValueError("fake agent runtime needs an 'Account: <slug>' line in the user text")
        slug = match.group(1)
        if role == "memory_writer":
            return await self._write_memory(memory_store_id, access, slug)
        return await self._brief(memory_store_id, slug)

    async def _write_memory(self, store_id: str, access: str, slug: str) -> AgentRunResult:
        if access == "read_only":
            return AgentRunResult(text=f"Read memory for {slug}; read-only access, nothing written.")
        snapshot = await self._memory.snapshot(store_id)
        tool_calls = []
        session_number = 0
        for filename, title in (("objections.md", "Objections"), ("strategy.md", "Strategy")):
            path = f"/accounts/{slug}/{filename}"
            current = snapshot.get(path, f"# {title} for {slug}\n")
            session_number = len(SESSION_LINE.findall(current)) + 1
            line = f"Session {session_number}: {title.lower()} updated from the interview.\n"
            self._memory.write(store_id, path, current + line)
            tool_calls.append({"name": "write", "input": {"path": path}})
        return AgentRunResult(
            text=f"Updated memory for {slug} (session {session_number}).", tool_calls=tool_calls
        )

    async def _brief(self, store_id: str, slug: str) -> AgentRunResult:
        strategy = (await self._memory.snapshot(store_id)).get(f"/accounts/{slug}/strategy.md", "")
        if len(SESSION_LINE.findall(strategy)) >= 2:
            return AgentRunResult(
                text=(
                    "Since our last session: a new objection and a competitive update "
                    f"changed the pitch order for {slug}."
                )
            )
        return AgentRunResult(text=f"First session for {slug}: no earlier memory to compare against.")
