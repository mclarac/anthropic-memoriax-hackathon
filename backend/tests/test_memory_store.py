"""ManagedMemoryStore against a recording fake of the AsyncAnthropic memory-store surface."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from memoria.memory.store import ManagedMemoryStore


class FakeMemories:
    """Serves list results in pages of `page_size` and records every call, like the SDK paginator."""

    def __init__(self, items: list[SimpleNamespace], page_size: int = 2) -> None:
        self.items = items
        self.page_size = page_size
        self.list_calls: list[dict] = []
        self.retrieve_calls: list[tuple[str, str]] = []
        self.in_flight = 0
        self.max_in_flight = 0

    def list(self, memory_store_id: str, **kwargs):
        self.list_calls.append({"memory_store_id": memory_store_id, **kwargs})
        items, size = self.items, self.page_size

        class Paginator:
            async def __aiter__(self):
                for start in range(0, len(items), size):
                    for item in items[start:start + size]:
                        yield item

        return Paginator()

    async def retrieve(self, memory_id: str, *, memory_store_id: str):
        self.retrieve_calls.append((memory_id, memory_store_id))
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0.005)
        self.in_flight -= 1
        item = next(i for i in self.items if i.id == memory_id)
        return SimpleNamespace(content=f"content of {item.path}")


class FakeMemoryStores:
    def __init__(self, memories: FakeMemories) -> None:
        self.memories = memories
        self.create_calls: list[dict] = []

    async def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return SimpleNamespace(id=f"memstore_{len(self.create_calls)}")


def make_client(items: list[SimpleNamespace] | None = None, page_size: int = 2):
    memories = FakeMemories(items or [], page_size)
    stores = FakeMemoryStores(memories)
    return SimpleNamespace(beta=SimpleNamespace(memory_stores=stores)), stores


def memory(path: str, kind: str = "memory") -> SimpleNamespace:
    return SimpleNamespace(id=f"mem_{path}", path=path, type=kind)


async def test_ensure_store_creates_with_tenant_metadata_and_records_it(tmp_path):
    client, stores = make_client()
    registry = tmp_path / "registry.json"

    store_id = await ManagedMemoryStore(client, registry).ensure_store("acme", "Acme Corp")

    assert store_id == "memstore_1"
    [call] = stores.create_calls
    assert call["name"] == "Memoria: Acme Corp"
    assert "sales memory" in call["description"]
    assert call["metadata"] == {"tenant_id": "acme", "app": "memoria"}
    assert json.loads(registry.read_text())["memory_stores"] == {"acme": "memstore_1"}


async def test_ensure_store_reuses_registry_across_instances(tmp_path):
    client, stores = make_client()
    registry = tmp_path / "registry.json"
    first = await ManagedMemoryStore(client, registry).ensure_store("acme", "Acme")

    second = await ManagedMemoryStore(client, registry).ensure_store("acme", "Acme")

    assert second == first
    assert len(stores.create_calls) == 1


async def test_each_tenant_gets_its_own_store(tmp_path):
    client, stores = make_client()
    store = ManagedMemoryStore(client, tmp_path / "registry.json")

    a = await store.ensure_store("acme", "Acme")
    b = await store.ensure_store("globex", "Globex")

    assert a != b
    assert len(stores.create_calls) == 2


async def test_concurrent_ensure_store_creates_once(tmp_path):
    client, stores = make_client()
    store = ManagedMemoryStore(client, tmp_path / "registry.json")

    ids = await asyncio.gather(*(store.ensure_store("acme", "Acme") for _ in range(5)))

    assert len(set(ids)) == 1
    assert len(stores.create_calls) == 1


async def test_ensure_store_preserves_unrelated_registry_keys(tmp_path):
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"environment": "env_1"}))
    client, _ = make_client()

    await ManagedMemoryStore(client, registry).ensure_store("acme", "Acme")

    data = json.loads(registry.read_text())
    assert data["environment"] == "env_1"
    assert data["memory_stores"] == {"acme": "memstore_1"}
    assert not list(tmp_path.glob("*.tmp"))


async def test_ensure_store_rejects_corrupt_registry(tmp_path):
    registry = tmp_path / "registry.json"
    registry.write_text("{not json")
    client, stores = make_client()

    with pytest.raises(ValueError, match="registry"):
        await ManagedMemoryStore(client, registry).ensure_store("acme", "Acme")
    assert stores.create_calls == []


async def test_snapshot_follows_pagination_to_the_end_sorted_by_path(tmp_path):
    paths = ["/z.md", "/accounts/a/strategy.md", "/README.md", "/accounts/a/objections.md", "/m.md"]
    client, stores = make_client([memory(p) for p in paths], page_size=2)

    snap = await ManagedMemoryStore(client, tmp_path / "r.json").snapshot("memstore_1")

    assert list(snap) == sorted(paths)
    assert snap["/m.md"] == "content of /m.md"
    [call] = stores.memories.list_calls
    assert call["memory_store_id"] == "memstore_1"
    assert call["path_prefix"] == "/"


async def test_snapshot_passes_prefix_through(tmp_path):
    client, stores = make_client([memory("/accounts/a/x.md")])

    await ManagedMemoryStore(client, tmp_path / "r.json").snapshot("s", "/accounts/a/")

    assert stores.memories.list_calls[0]["path_prefix"] == "/accounts/a/"


async def test_snapshot_skips_non_file_entries(tmp_path):
    client, stores = make_client([
        memory("/accounts/", kind="memory_prefix"), memory("/a.md"),
    ])

    snap = await ManagedMemoryStore(client, tmp_path / "r.json").snapshot("s")

    assert snap == {"/a.md": "content of /a.md"}
    assert [c[0] for c in stores.memories.retrieve_calls] == ["mem_/a.md"]


async def test_snapshot_bounds_concurrent_retrievals_at_eight(tmp_path):
    client, stores = make_client([memory(f"/f{i:02}.md") for i in range(30)], page_size=10)

    snap = await ManagedMemoryStore(client, tmp_path / "r.json").snapshot("s")

    assert len(snap) == 30
    assert 1 < stores.memories.max_in_flight <= 8


async def test_snapshot_of_empty_store_is_empty(tmp_path):
    client, _ = make_client([])

    assert await ManagedMemoryStore(client, tmp_path / "r.json").snapshot("s") == {}


async def test_snapshot_treats_null_content_as_empty_string(tmp_path):
    client, stores = make_client([memory("/a.md")])

    async def null_content(memory_id, *, memory_store_id):
        return SimpleNamespace(content=None)

    stores.memories.retrieve = null_content

    assert await ManagedMemoryStore(client, tmp_path / "r.json").snapshot("s") == {"/a.md": ""}
