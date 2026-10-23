"""ManagedAgentRuntime against a recording fake of the AsyncAnthropic sessions surface."""

from __future__ import annotations

import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest

from memoria.chain_prompts import MEMORY_WRITER_SYSTEM, MODEL, STRATEGY_ANSWER_SYSTEM
from memoria.memory.agents import AgentRunError, ManagedAgentRuntime
from memoria.ports import AgentRunResult


def text_message(*texts: str) -> SimpleNamespace:
    return SimpleNamespace(
        type="agent.message",
        content=[SimpleNamespace(type="text", text=t) for t in texts],
    )


def tool_use(name: str, **input_: object) -> SimpleNamespace:
    return SimpleNamespace(type="agent.tool_use", name=name, input=input_)


def idle(stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(type="session.status_idle", stop_reason=SimpleNamespace(type=stop_reason))


def session_error() -> SimpleNamespace:
    return SimpleNamespace(
        type="session.error", error=SimpleNamespace(type="model_overloaded_error", message="overloaded")
    )


class FakeStream:
    def __init__(self, events: list[SimpleNamespace], log: list[str], hang: bool) -> None:
        self._events, self._log, self._hang = events, log, hang
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.closed = True

    async def __aiter__(self):
        for event in self._events:
            yield event
        if self._hang:
            await asyncio.Event().wait()


class FakeClient:
    """Records every SDK call in order; `script` is the event list each session's stream replays."""

    def __init__(self, script: list[SimpleNamespace] | None = None, hang: bool = False) -> None:
        self.script = script if script is not None else [text_message("done"), idle()]
        self.hang = hang
        self.log: list[str] = []
        self.agent_calls: list[dict] = []
        self.environment_calls: list[dict] = []
        self.session_calls: list[dict] = []
        self.sent: list[tuple[str, list[dict]]] = []
        self.streams: list[FakeStream] = []
        self.beta = SimpleNamespace(
            agents=SimpleNamespace(create=self._create_agent),
            environments=SimpleNamespace(create=self._create_environment),
            sessions=SimpleNamespace(
                create=self._create_session,
                events=SimpleNamespace(stream=self._stream, send=self._send),
            ),
        )

    async def _create_agent(self, **kwargs):
        self.agent_calls.append(kwargs)
        return SimpleNamespace(id=f"agent_{len(self.agent_calls)}")

    async def _create_environment(self, **kwargs):
        self.environment_calls.append(kwargs)
        return SimpleNamespace(id=f"env_{len(self.environment_calls)}")

    async def _create_session(self, **kwargs):
        self.log.append("session.create")
        self.session_calls.append(kwargs)
        return SimpleNamespace(id=f"sesn_{len(self.session_calls)}")

    async def _stream(self, session_id, **kwargs):
        self.log.append("stream.open")
        stream = FakeStream(self.script, self.log, self.hang)
        self.streams.append(stream)
        return stream

    async def _send(self, session_id, *, events):
        self.log.append("send")
        self.sent.append((session_id, events))


def runtime(client: FakeClient, tmp_path, **kwargs) -> ManagedAgentRuntime:
    return ManagedAgentRuntime(client, tmp_path / "registry.json", **kwargs)


async def run(rt: ManagedAgentRuntime, role="memory_writer", access="read_write", user="hello"):
    return await rt.run(role=role, memory_store_id="memstore_1", access=access, user=user, title="t")


async def test_run_collects_text_and_tool_calls_until_idle(tmp_path):
    client = FakeClient([
        text_message("Checking memory. "),
        tool_use("bash", command="ls /mnt/memory"),
        text_message("Saved ", "it."),
        tool_use("write", path="/mnt/memory/a.md"),
        idle(),
    ])

    result = await run(runtime(client, tmp_path))

    assert result == AgentRunResult(
        text="Checking memory. Saved it.",
        tool_calls=[
            {"name": "bash", "input": {"command": "ls /mnt/memory"}},
            {"name": "write", "input": {"path": "/mnt/memory/a.md"}},
        ],
    )


async def test_run_ignores_events_after_idle_and_non_text_blocks(tmp_path):
    client = FakeClient([
        SimpleNamespace(type="agent.message", content=[SimpleNamespace(type="thinking", text="x")]),
        text_message("answer"),
        idle(),
        text_message("never read"),
    ])

    result = await run(runtime(client, tmp_path))

    assert result.text == "answer"
    assert client.streams[0].closed


async def test_stream_is_opened_before_the_user_message_is_sent(tmp_path):
    client = FakeClient()

    await run(runtime(client, tmp_path), user="Account: acme")

    assert client.log == ["session.create", "stream.open", "send"]
    [(session_id, events)] = client.sent
    assert session_id == "sesn_1"
    assert events == [{"type": "user.message", "content": [{"type": "text", "text": "Account: acme"}]}]


@pytest.mark.parametrize("access", ["read_write", "read_only"])
async def test_session_attaches_the_store_with_access_and_instructions(tmp_path, access):
    client = FakeClient()

    await run(runtime(client, tmp_path), access=access)

    [call] = client.session_calls
    assert call["title"] == "t"
    [resource] = call["resources"]
    assert resource["type"] == "memory_store"
    assert resource["memory_store_id"] == "memstore_1"
    assert resource["access"] == access
    assert "/mnt/memory/" in resource["instructions"]
    assert access.replace("_", " ") in resource["instructions"]


async def test_session_uses_the_roles_agent_and_the_environment(tmp_path):
    client = FakeClient()
    rt = runtime(client, tmp_path)

    await run(rt, role="memory_writer")
    await run(rt, role="briefer", access="read_only")

    writer_call, briefer_call = client.session_calls
    assert writer_call["agent"] != briefer_call["agent"]
    assert writer_call["environment_id"] == briefer_call["environment_id"] == "env_1"


async def test_agents_are_created_with_prompt_toolset_and_metadata(tmp_path):
    client = FakeClient()
    rt = runtime(client, tmp_path)

    await run(rt, role="memory_writer")
    await run(rt, role="briefer", access="read_only")

    by_role = {c["metadata"]["role"]: c for c in client.agent_calls}
    assert by_role["memory_writer"]["system"] == MEMORY_WRITER_SYSTEM
    assert by_role["briefer"]["system"] == STRATEGY_ANSWER_SYSTEM
    for call in by_role.values():
        assert call["model"] == MODEL
        assert call["tools"] == [{"type": "agent_toolset_20260401"}]
        assert call["metadata"]["app"] == "memoria"


async def test_model_override_reaches_the_agents(tmp_path):
    client = FakeClient()

    await run(runtime(client, tmp_path, model="claude-test-model"))

    assert client.agent_calls[0]["model"] == "claude-test-model"


async def test_environment_is_cloud_with_limited_networking_and_no_hosts(tmp_path):
    client = FakeClient()

    await run(runtime(client, tmp_path))

    [call] = client.environment_calls
    assert call["config"]["type"] == "cloud"
    networking = call["config"]["networking"]
    assert networking["type"] == "limited"
    assert not networking.get("allowed_hosts")
    assert not networking.get("allow_package_managers")
    assert not networking.get("allow_mcp_servers")


async def test_resources_are_provisioned_once_and_reused_by_a_new_runtime(tmp_path):
    client = FakeClient()
    await run(runtime(client, tmp_path))
    await run(runtime(client, tmp_path))
    await run(runtime(client, tmp_path), role="briefer", access="read_only")

    assert len(client.environment_calls) == 1
    assert len(client.agent_calls) == 2
    registry = json.loads((tmp_path / "registry.json").read_text())
    assert registry["environment"] == "env_1"
    assert registry["agents"]["memory_writer"]["prompt_sha256"] == hashlib.sha256(
        MEMORY_WRITER_SYSTEM.encode()
    ).hexdigest()


async def test_concurrent_runs_provision_each_resource_once(tmp_path):
    client = FakeClient()
    rt = runtime(client, tmp_path)

    await asyncio.gather(*(run(rt) for _ in range(4)))

    assert len(client.environment_calls) == 1
    assert len(client.agent_calls) == 1


async def test_changed_prompt_creates_a_new_agent_and_updates_the_registry(tmp_path):
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps({
        "environment": "env_old",
        "agents": {"memory_writer": {"id": "agent_stale", "prompt_sha256": "0" * 64}},
    }))
    client = FakeClient()

    await run(runtime(client, tmp_path))

    assert len(client.agent_calls) == 1
    assert client.session_calls[0]["agent"] == "agent_1"
    assert client.session_calls[0]["environment_id"] == "env_old"
    stored = json.loads(registry_path.read_text())["agents"]["memory_writer"]
    assert stored["id"] == "agent_1"
    assert stored["prompt_sha256"] == hashlib.sha256(MEMORY_WRITER_SYSTEM.encode()).hexdigest()


async def test_matching_prompt_hash_reuses_the_registered_agent(tmp_path):
    (tmp_path / "registry.json").write_text(json.dumps({
        "environment": "env_old",
        "agents": {"briefer": {
            "id": "agent_kept", "prompt_sha256": hashlib.sha256(STRATEGY_ANSWER_SYSTEM.encode()).hexdigest(),
        }},
    }))
    client = FakeClient()

    await run(runtime(client, tmp_path), role="briefer", access="read_only")

    assert client.agent_calls == []
    assert client.environment_calls == []
    assert client.session_calls[0]["agent"] == "agent_kept"


async def test_session_error_event_raises_with_the_error_detail(tmp_path):
    client = FakeClient([text_message("partial"), session_error()])

    with pytest.raises(AgentRunError, match="model_overloaded_error"):
        await run(runtime(client, tmp_path))
    assert client.streams[0].closed


@pytest.mark.parametrize("reason", ["retries_exhausted", "refusal", "budget_reached", "requires_action"])
async def test_idle_for_any_reason_but_end_turn_raises(tmp_path, reason):
    client = FakeClient([text_message("x"), idle(reason)])

    with pytest.raises(AgentRunError, match=reason):
        await run(runtime(client, tmp_path))


async def test_stream_ending_without_idle_raises(tmp_path):
    client = FakeClient([text_message("x")])

    with pytest.raises(AgentRunError, match="ended before"):
        await run(runtime(client, tmp_path))


async def test_timeout_raises_agent_run_error_and_closes_the_stream(tmp_path):
    client = FakeClient([text_message("working")], hang=True)

    with pytest.raises(AgentRunError, match="timed out after 0.05s"):
        await run(runtime(client, tmp_path, timeout_s=0.05))
    assert client.streams[0].closed
