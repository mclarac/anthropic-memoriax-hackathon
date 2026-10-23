"""The memory fakes against docs/contract.md "Fake mode behavior"."""

from __future__ import annotations

import pytest

from memoria.fakes.memory import FakeAgentRuntime, FakeMemoryStore
from memoria.ports import diff_snapshots


async def write_memory(runtime: FakeAgentRuntime, store_id: str, slug: str = "acme", access="read_write"):
    return await runtime.run(
        role="memory_writer", memory_store_id=store_id, access=access,
        user=f"Account: {slug}\nRep: dana\nTranscript: ...", title="build",
    )


async def brief(runtime: FakeAgentRuntime, store_id: str, slug: str = "acme"):
    return await runtime.run(
        role="briefer", memory_store_id=store_id, access="read_only",
        user=f"Account: {slug}\nQUESTION: what now?", title="brief",
    )


async def test_store_id_is_derived_from_tenant_and_ensure_is_idempotent():
    memory = FakeMemoryStore()

    first = await memory.ensure_store("acme", "Acme")
    second = await memory.ensure_store("acme", "Acme Renamed")

    assert first == second == "fake-store-acme"


async def test_snapshot_is_sorted_filtered_by_prefix_and_isolated_per_store():
    memory = FakeMemoryStore()
    a = await memory.ensure_store("a", "A")
    b = await memory.ensure_store("b", "B")
    memory.write(a, "/z.md", "z")
    memory.write(a, "/accounts/x/s.md", "s")
    memory.write(b, "/other.md", "o")

    assert list(await memory.snapshot(a)) == ["/accounts/x/s.md", "/z.md"]
    assert await memory.snapshot(a, "/accounts/") == {"/accounts/x/s.md": "s"}
    assert await memory.snapshot(b) == {"/other.md": "o"}


async def test_snapshot_returns_a_copy():
    memory = FakeMemoryStore()
    store = await memory.ensure_store("a", "A")
    memory.write(store, "/a.md", "1")

    (await memory.snapshot(store))["/a.md"] = "mutated"

    assert (await memory.snapshot(store))["/a.md"] == "1"


async def test_unknown_store_snapshots_as_empty():
    assert await FakeMemoryStore().snapshot("fake-store-ghost") == {}


async def test_first_memory_writer_run_adds_objections_and_strategy():
    memory = FakeMemoryStore()
    store = await memory.ensure_store("acme", "Acme")
    before = await memory.snapshot(store)

    result = await write_memory(FakeAgentRuntime(memory), store)

    changes = diff_snapshots(before, await memory.snapshot(store))
    assert [(c.path, c.change) for c in changes] == [
        ("/accounts/acme/objections.md", "added"),
        ("/accounts/acme/strategy.md", "added"),
    ]
    assert "acme" in result.text
    assert {c["input"]["path"] for c in result.tool_calls} == {c.path for c in changes}


async def test_second_run_produces_modified_diffs():
    memory = FakeMemoryStore()
    store = await memory.ensure_store("acme", "Acme")
    runtime = FakeAgentRuntime(memory)
    await write_memory(runtime, store)
    before = await memory.snapshot(store)

    await write_memory(runtime, store)

    changes = diff_snapshots(before, await memory.snapshot(store))
    assert [(c.path, c.change) for c in changes] == [
        ("/accounts/acme/objections.md", "modified"),
        ("/accounts/acme/strategy.md", "modified"),
    ]
    assert changes[0].after.count("Session ") == 2


async def test_accounts_are_kept_apart():
    memory = FakeMemoryStore()
    store = await memory.ensure_store("acme", "Acme")
    runtime = FakeAgentRuntime(memory)

    await write_memory(runtime, store, "acme")
    await write_memory(runtime, store, "globex")

    snap = await memory.snapshot(store)
    assert snap["/accounts/globex/strategy.md"].count("Session ") == 1
    assert snap["/accounts/acme/strategy.md"].count("Session ") == 1


async def test_read_only_memory_writer_does_not_write():
    memory = FakeMemoryStore()
    store = await memory.ensure_store("acme", "Acme")

    result = await write_memory(FakeAgentRuntime(memory), store, access="read_only")

    assert await memory.snapshot(store) == {}
    assert result.tool_calls == []


async def test_briefer_says_first_session_until_two_sessions_are_remembered():
    memory = FakeMemoryStore()
    store = await memory.ensure_store("acme", "Acme")
    runtime = FakeAgentRuntime(memory)

    assert (await brief(runtime, store)).text.startswith("First session for acme:")
    await write_memory(runtime, store)
    assert (await brief(runtime, store)).text.startswith("First session for acme:")
    await write_memory(runtime, store)
    assert (await brief(runtime, store)).text.startswith("Since our last session:")


async def test_briefer_never_writes():
    memory = FakeMemoryStore()
    store = await memory.ensure_store("acme", "Acme")
    runtime = FakeAgentRuntime(memory)
    await write_memory(runtime, store)
    before = await memory.snapshot(store)

    await brief(runtime, store)

    assert await memory.snapshot(store) == before


async def test_runs_are_deterministic():
    async def full_run():
        memory = FakeMemoryStore()
        store = await memory.ensure_store("acme", "Acme")
        runtime = FakeAgentRuntime(memory)
        await write_memory(runtime, store)
        await write_memory(runtime, store)
        return await memory.snapshot(store), (await brief(runtime, store)).text

    assert await full_run() == await full_run()


@pytest.mark.parametrize("role", ["memory_writer", "briefer"])
async def test_user_text_without_an_account_line_is_rejected(role):
    memory = FakeMemoryStore()
    store = await memory.ensure_store("acme", "Acme")

    with pytest.raises(ValueError, match="Account:"):
        await FakeAgentRuntime(memory).run(
            role=role, memory_store_id=store, access="read_write", user="no slug here", title="t"
        )
