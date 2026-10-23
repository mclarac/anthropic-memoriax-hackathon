import json
import os

import pytest

from memoria.models import TenantProfile
from memoria.storage import NotFoundError, Storage, document_media_type, sanitize_filename


@pytest.fixture
def storage(tmp_path):
    return Storage(tmp_path)


def make_profile(name="Acme"):
    return TenantProfile(name=name, offering_summary="Payroll software")


def test_tenant_round_trip_and_ids_are_12_hex(storage):
    created = storage.create_tenant(make_profile())
    assert len(created.id) == 12 and int(created.id, 16) >= 0
    assert storage.get_tenant(created.id) == created


def test_list_tenants_sorted_by_name(storage):
    storage.create_tenant(make_profile("Zeta"))
    storage.create_tenant(make_profile("alpha"))
    assert [t.profile.name for t in storage.list_tenants()] == ["alpha", "Zeta"]


def test_list_tenants_empty_when_nothing_stored(storage):
    assert storage.list_tenants() == []


def test_unknown_tenant_raises_not_found(storage):
    with pytest.raises(NotFoundError):
        storage.get_tenant("000000000000")


@pytest.mark.parametrize("bad_id", ["../etc", "..", "abc", "ZZZZZZZZZZZZ", "0123456789ab/../x"])
def test_malformed_ids_are_not_found_rather_than_resolved(storage, bad_id):
    with pytest.raises(NotFoundError):
        storage.get_tenant(bad_id)
    with pytest.raises(NotFoundError):
        storage.get_session(bad_id)
    with pytest.raises(NotFoundError):
        storage.rendered_file(bad_id, "a.pdf")


def test_save_tenant_persists_memory_store_id(storage):
    tenant = storage.create_tenant(make_profile())
    tenant.memory_store_id = "memstore_1"
    storage.save_tenant(tenant)
    assert storage.get_tenant(tenant.id).memory_store_id == "memstore_1"


def test_add_document_stores_bytes_and_records_ref_on_tenant(storage):
    tenant = storage.create_tenant(make_profile())
    ref = storage.add_document(
        tenant.id, filename="Q3 notes.txt", media_type="text/plain", data=b"hello",
        scope="account", account_slug="globex",
    )
    assert ref.filename == "Q3_notes.txt"
    assert ref.size_bytes == 5 and ref.scope == "account" and ref.account_slug == "globex"
    assert storage.get_tenant(tenant.id).documents == [ref]
    assert storage.read_document(tenant.id, ref) == b"hello"


def test_same_filename_uploaded_twice_does_not_collide(storage):
    tenant = storage.create_tenant(make_profile())
    kwargs = dict(filename="a.md", media_type="text/markdown", scope="tenant", account_slug=None)
    first = storage.add_document(tenant.id, data=b"one", **kwargs)
    second = storage.add_document(tenant.id, data=b"two", **kwargs)
    assert storage.read_document(tenant.id, first) == b"one"
    assert storage.read_document(tenant.id, second) == b"two"


def test_add_document_for_unknown_tenant_raises(storage):
    with pytest.raises(NotFoundError):
        storage.add_document("000000000000", filename="a.md", media_type="text/markdown", data=b"",
                             scope="tenant", account_slug=None)


def test_session_round_trip(storage):
    session = storage.create_session("aaaaaaaaaaaa", "globex", "dana")
    session.memory_snapshot = {"/a.md": "x"}
    storage.save_session(session)
    loaded = storage.get_session(session.id)
    assert loaded == session
    assert loaded.phase == "interview" and loaded.rep_slug == "dana"


def test_unknown_session_raises(storage):
    with pytest.raises(NotFoundError):
        storage.get_session("000000000000")


def test_failed_write_keeps_previous_content_and_leaves_no_temp_files(storage, monkeypatch, tmp_path):
    session = storage.create_session("aaaaaaaaaaaa", "globex", "dana")
    original = storage.get_session(session.id)

    def explode(src, dst):
        raise OSError("disk full")

    session.phase = "building"
    monkeypatch.setattr(os, "replace", explode)
    with pytest.raises(OSError, match="disk full"):
        storage.save_session(session)
    monkeypatch.undo()

    assert storage.get_session(session.id) == original
    leftovers = [p.name for p in (tmp_path / "sessions" / session.id).iterdir()]
    assert leftovers == ["session.json"]


def test_saved_json_is_valid_json_on_disk(storage, tmp_path):
    session = storage.create_session("aaaaaaaaaaaa", "globex", "dana")
    on_disk = json.loads((tmp_path / "sessions" / session.id / "session.json").read_text())
    assert on_disk["id"] == session.id


def test_rendered_file_resolves_files_in_session_directory(storage):
    session = storage.create_session("aaaaaaaaaaaa", "globex", "dana")
    (storage.rendered_dir(session.id) / "deck.pptx").write_bytes(b"pptx")
    assert storage.rendered_file(session.id, "deck.pptx").read_bytes() == b"pptx"


def test_rendered_file_refuses_traversal_and_missing(storage, tmp_path):
    session = storage.create_session("aaaaaaaaaaaa", "globex", "dana")
    storage.rendered_dir(session.id)
    (tmp_path / "secret.txt").write_text("nope")
    for name in ["../../secret.txt", "..", "deck.pptx", "a/b.txt"]:
        with pytest.raises(NotFoundError):
            storage.rendered_file(session.id, name)


def test_rendered_file_refuses_symlink_leaving_the_directory(storage, tmp_path):
    session = storage.create_session("aaaaaaaaaaaa", "globex", "dana")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    (storage.rendered_dir(session.id) / "link.md").symlink_to(outside)
    with pytest.raises(NotFoundError):
        storage.rendered_file(session.id, "link.md")


def test_rendered_file_does_not_cross_sessions(storage):
    first = storage.create_session("aaaaaaaaaaaa", "globex", "dana")
    second = storage.create_session("aaaaaaaaaaaa", "globex", "dana")
    (storage.rendered_dir(first.id) / "deck.pptx").write_bytes(b"x")
    storage.rendered_dir(second.id)
    with pytest.raises(NotFoundError):
        storage.rendered_file(second.id, "deck.pptx")


@pytest.mark.parametrize("raw, expected", [
    ("report.pdf", "report.pdf"),
    ("../../etc/passwd", "passwd"),
    ("C:\\Users\\x\\plan v2.docx", "plan_v2.docx"),
    (".hidden", "hidden"),
    ("", "file"),
    ("...", "file"),
    ("naïve café.md", "na_ve_caf_.md"),
])
def test_sanitize_filename(raw, expected):
    assert sanitize_filename(raw) == expected


def test_sanitize_filename_caps_length_and_keeps_extension():
    cleaned = sanitize_filename("a" * 500 + ".pdf")
    assert len(cleaned) <= 120 and cleaned.endswith(".pdf")


@pytest.mark.parametrize("name, expected", [
    ("a.PDF", "application/pdf"),
    ("a.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ("a.md", "text/markdown"),
    ("a.txt", "text/plain"),
    ("a.exe", None),
    ("noextension", None),
])
def test_document_media_type(name, expected):
    assert document_media_type(name) == expected


def test_dataset_registry_round_trip_and_defaults(storage):
    assert storage.dataset_tenant_id("tenant-a") is None
    storage.remember_dataset_tenant("tenant-a", "aaaaaaaaaaaa")
    storage.remember_dataset_tenant("tenant-b", "bbbbbbbbbbbb")
    assert storage.dataset_tenant_id("tenant-a") == "aaaaaaaaaaaa"
    assert Storage(storage.data_dir).dataset_tenant_id("tenant-b") == "bbbbbbbbbbbb"
