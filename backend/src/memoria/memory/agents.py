"""Managed Agents runtime: memory writer and briefer roles, one persistent agent each."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any, Literal

import anthropic

from memoria.chain_prompts import MEMORY_WRITER_SYSTEM, MODEL, STRATEGY_ANSWER_SYSTEM
from memoria.memory.store import JsonRegistry
from memoria.ports import AgentRunResult

Role = Literal["memory_writer", "briefer"]

ROLE_SYSTEMS: dict[str, str] = {
    "memory_writer": MEMORY_WRITER_SYSTEM,
    "briefer": STRATEGY_ANSWER_SYSTEM,
}
AGENT_NAMES = {"memory_writer": "Memoria memory writer", "briefer": "Memoria briefer"}


class AgentRunError(RuntimeError):
    """A Managed Agents session failed, stopped without finishing its turn, or ran out of time."""


def _prompt_hash(system: str) -> str:
    return hashlib.sha256(system.encode()).hexdigest()


class ManagedAgentRuntime:
    """Implements ports.AgentRuntime.

    The environment and one agent per role are created on first use and
    recorded in the registry. An agent whose system prompt changed since it was
    created is replaced, because agents are pinned to the prompt they were
    created with.
    """

    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        registry_path: Path,
        model: str = MODEL,
        timeout_s: float = 600,
    ) -> None:
        self._client = client
        self._registry = JsonRegistry(registry_path)
        self._model = model
        self._timeout_s = timeout_s
        self._provision_lock = asyncio.Lock()

    async def run(
        self,
        *,
        role: Role,
        memory_store_id: str,
        access: Literal["read_write", "read_only"],
        user: str,
        title: str,
    ) -> AgentRunResult:
        agent_id, environment_id = await self._ensure_agent_and_environment(role)
        session = await self._client.beta.sessions.create(
            agent=agent_id,
            environment_id=environment_id,
            title=title,
            resources=[{
                "type": "memory_store",
                "memory_store_id": memory_store_id,
                "access": access,
                "instructions": (
                    f"This tenant's long-term memory, mounted under /mnt/memory/. "
                    f"Access is {access.replace('_', ' ')}."
                ),
            }],
        )
        try:
            async with asyncio.timeout(self._timeout_s) as deadline:
                return await self._converse(session.id, user)
        except TimeoutError:
            if not deadline.expired():
                raise
            raise AgentRunError(
                f"{role} session {session.id} timed out after {self._timeout_s}s"
            ) from None

    async def _converse(self, session_id: str, user: str) -> AgentRunResult:
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        # The stream must be open before the message is sent, or early events are missed.
        async with await self._client.beta.sessions.events.stream(session_id) as stream:
            await self._client.beta.sessions.events.send(
                session_id,
                events=[{"type": "user.message", "content": [{"type": "text", "text": user}]}],
            )
            async for event in stream:
                if event.type == "agent.message":
                    text_parts.extend(b.text for b in event.content if b.type == "text")
                elif event.type == "agent.tool_use":
                    tool_calls.append({"name": event.name, "input": dict(event.input)})
                elif event.type == "session.error":
                    raise AgentRunError(
                        f"session {session_id} failed: {event.error.type}: "
                        f"{getattr(event.error, 'message', '')}"
                    )
                elif event.type == "session.status_idle":
                    reason = event.stop_reason.type
                    if reason != "end_turn":
                        raise AgentRunError(f"session {session_id} stopped without finishing: {reason}")
                    return AgentRunResult(text="".join(text_parts), tool_calls=tool_calls)
        raise AgentRunError(f"session {session_id} stream ended before the agent went idle")

    async def _ensure_agent_and_environment(self, role: Role) -> tuple[str, str]:
        # One lock for both so concurrent first runs cannot each create their own copy.
        async with self._provision_lock:
            data = self._registry.read()
            environment_id = data.get("environment") or await self._create_environment()

            system = ROLE_SYSTEMS[role]
            digest = _prompt_hash(system)
            recorded = data.get("agents", {}).get(role)
            if recorded and recorded["prompt_sha256"] == digest:
                return recorded["id"], environment_id

            agent = await self._client.beta.agents.create(
                name=AGENT_NAMES[role],
                model=self._model,
                system=system,
                tools=[{"type": "agent_toolset_20260401"}],
                metadata={"app": "memoria", "role": role},
            )
            self._registry.update(
                lambda d: d.setdefault("agents", {}).__setitem__(
                    role, {"id": agent.id, "prompt_sha256": digest}
                )
            )
            return agent.id, environment_id

    async def _create_environment(self) -> str:
        # Memory is plain files under /mnt/memory/, so the sandbox needs no outbound access at all.
        environment = await self._client.beta.environments.create(
            name="memoria-environment",
            config={"type": "cloud", "networking": {"type": "limited"}},
            metadata={"app": "memoria"},
        )
        self._registry.update(lambda d: d.__setitem__("environment", environment.id))
        return environment.id
