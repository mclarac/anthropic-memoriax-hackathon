"""Interfaces between the orchestrator and everything that talks to the outside world.

Each port has a real adapter (Anthropic, Managed Agents, Kokoro) and a fake
adapter for tests and MEMORIA_MODE=fake. The orchestrator depends only on
these protocols, never on an SDK directly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from memoria.models import MemoryChange


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class LLMResult:
    text: str
    data: dict[str, Any] | None = None  # parsed structured output, when a schema was given
    usage: Usage = field(default_factory=Usage)
    stop_reason: str | None = None


@dataclass
class LLMRequest:
    """One Messages API call. `stage` lets fakes and logs know which chain stage is calling."""
    stage: str
    system: str
    user: str
    max_tokens: int
    tenant_block: str | None = None  # sent after the system prompt, marked cache_control
    schema: dict[str, Any] | None = None
    effort: Literal["low", "medium", "high"] | None = None
    documents: list[dict[str, Any]] = field(default_factory=list)  # Files API document blocks
    tools: list[str] = field(default_factory=list)  # server tools: "web_search", "web_fetch"
    max_tool_calls: int = 0
    finalize_user: str | None = None  # research: final turn after the tool loop, structured


class LLM(Protocol):
    async def complete(self, req: LLMRequest) -> LLMResult: ...

    def stream(self, req: LLMRequest) -> AsyncIterator[str]:
        """Yield text deltas. No schema, no tools."""
        ...


@dataclass
class AgentRunResult:
    text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class AgentRuntime(Protocol):
    """Managed Agents sessions with the tenant's memory store attached."""

    async def run(
        self,
        *,
        role: Literal["memory_writer", "briefer"],
        memory_store_id: str,
        access: Literal["read_write", "read_only"],
        user: str,
        title: str,
    ) -> AgentRunResult: ...


class MemoryStore(Protocol):
    async def ensure_store(self, tenant_id: str, tenant_name: str) -> str:
        """Create the tenant's store if needed; return its id."""
        ...

    async def snapshot(self, memory_store_id: str, path_prefix: str = "/") -> dict[str, str]:
        """Return {path: content} for every memory under the prefix."""
        ...


def diff_snapshots(before: dict[str, str], after: dict[str, str]) -> list[MemoryChange]:
    """Pure diff of two snapshots, sorted by path."""
    changes: list[MemoryChange] = []
    for path in sorted(before.keys() | after.keys()):
        old, new = before.get(path), after.get(path)
        if old == new:
            continue
        if old is None:
            changes.append(MemoryChange(path=path, change="added", after=new))
        elif new is None:
            changes.append(MemoryChange(path=path, change="removed", before=old))
        else:
            changes.append(MemoryChange(path=path, change="modified", before=old, after=new))
    return changes


class TTS(Protocol):
    async def synthesize(self, text: str, voice: str | None = None) -> bytes:
        """Return WAV bytes."""
        ...
