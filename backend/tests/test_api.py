import logging
import threading
from pathlib import Path

import pytest
from conftest import Doubles, brief, full_script, plan_entry
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from memoria.app import Ports, build_ports, create_app
from memoria.config import Settings
from memoria.models import (
    InterviewComplete,
    MemoriaDelta,
    MemoriaSentence,
    MemoriaTurnDone,
    SlotsChanged,
    SlotUpdate,
    Turn,
)

PROFILE = {"name": "Acme", "offering_summary": "Payroll software", "brand_voice": "plain"}
ORIGIN = "http://localhost:3000"


class ScriptedEngine:
    """Interview engine double: one question per turn, fails on the word 'explode'."""

    def __init__(self, llm, today, max_rep_turns=25):
        self.utterances = []

    async def opening(self, session, tenant):
        session.turns.append(Turn(speaker="memoria", text="Who is the buyer?"))
        yield MemoriaDelta(text="Who is ")
        yield MemoriaSentence(index=0, text="Who is the buyer?")
        yield MemoriaTurnDone(text="Who is the buyer?")

    async def handle_utterance(self, session, tenant, text):
        if text == "explode":
            raise RuntimeError("interviewer exploded")
        session.turns.append(Turn(speaker="rep", text=text))
        self.utterances.append(text)
        update = SlotUpdate(slot="pain", value=text, status="confirmed", evidence_quote=text)
        session.board.apply([update])
        yield MemoriaDelta(text="Thanks.")
        yield SlotsChanged(updates=[update], board=session.board)
        yield MemoriaTurnDone(text="Thanks.")
        if len(self.utterances) == 2:
            yield InterviewComplete(reason="slots_filled")


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, mode="fake", data_dir=tmp_path)


@pytest.fixture(autouse=True)
def scripted_engine(monkeypatch):
    monkeypatch.setattr("memoria.app.InterviewEngine", ScriptedEngine)


@pytest.fixture
def client(settings, doubles, render_recorder):
    ports = Ports(llm=doubles.llm, agents=doubles.agents, memory=doubles.memory, tts=doubles.tts)
    with TestClient(create_app(settings, ports)) as test_client:
        yield test_client


@pytest.fixture
def tenant(client):
    return client.post("/api/tenants", json=PROFILE).json()


@pytest.fixture
def session(client, tenant):
    return client.post("/api/sessions", json={
        "tenant_id": tenant["id"], "account_slug": "globex", "rep_slug": "dana"}).json()


def ws_url(session_id):
    return f"/api/sessions/{session_id}/ws"


def collect_until(ws, stop_type):
    events = []
    while True:
        event = ws.receive_json()
        events.append(event)
        if event["type"] == stop_type:
            return events


# Settings and wiring

def test_settings_defaults(monkeypatch):
    for name in ["MEMORIA_MODE", "MEMORIA_DATA_DIR", "MEMORIA_TTS_URL", "MEMORIA_MODEL",
                 "MEMORIA_CORS_ORIGINS", "ANTHROPIC_API_KEY"]:
        monkeypatch.delenv(name, raising=False)
    s = Settings(_env_file=None)
    assert s.mode == "live" and s.data_dir == Path("./data") and s.tts_url == "http://tts:8880"
    assert s.model == "claude-sonnet-5-5" and s.cors_origins == ["http://localhost:3000"]
    assert s.anthropic_api_key is None


def test_settings_read_environment(monkeypatch):
    monkeypatch.setenv("MEMORIA_MODE", "fake")
    monkeypatch.setenv("MEMORIA_DATA_DIR", "/tmp/memoria-x")
    monkeypatch.setenv("MEMORIA_TTS_URL", "http://localhost:9")
    monkeypatch.setenv("MEMORIA_MODEL", "some-model")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    s = Settings(_env_file=None)
    assert (s.mode, s.data_dir, s.tts_url, s.model) == ("fake", Path("/tmp/memoria-x"),
                                                        "http://localhost:9", "some-model")
    assert s.anthropic_api_key.get_secret_value() == "sk-test"


@pytest.mark.parametrize("raw", ["http://a:1,http://b:2", '["http://a:1", "http://b:2"]'])
def test_cors_origins_accept_comma_separated_and_json(monkeypatch, raw):
    monkeypatch.setenv("MEMORIA_CORS_ORIGINS", raw)
    assert Settings(_env_file=None).cors_origins == ["http://a:1", "http://b:2"]


def test_invalid_mode_is_rejected(monkeypatch):
    monkeypatch.setenv("MEMORIA_MODE", "demo")
    with pytest.raises(ValueError):
        Settings(_env_file=None)


def test_live_mode_without_api_key_fails_fast_with_a_clear_message(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY is required when MEMORIA_MODE=live"):
        create_app(Settings(_env_file=None, mode="live", data_dir=tmp_path))


def test_live_mode_builds_real_adapters_when_a_key_is_present(tmp_path):
    from memoria.llm import AnthropicLLM
    from memoria.tts import KokoroTTS

    ports = build_ports(Settings(_env_file=None, mode="live", data_dir=tmp_path, anthropic_api_key="sk-x",
                                 tts_url="http://tts.test:1"))
    assert isinstance(ports.llm, AnthropicLLM) and isinstance(ports.tts, KokoroTTS)


def test_fake_mode_needs_no_api_key_and_uses_one_shared_memory(tmp_path):
    ports = build_ports(Settings(_env_file=None, mode="fake", data_dir=tmp_path))
    assert type(ports.llm).__name__ == "FakeLLM"
    assert ports.agents._memory is ports.memory


# REST

def test_health_reports_mode(client):
    assert client.get("/api/health").json() == {"status": "ok", "mode": "fake"}


def test_tenant_create_get_list(client):
    created = client.post("/api/tenants", json=PROFILE)
    assert created.status_code == 201
    tenant = created.json()
    assert tenant["profile"]["name"] == "Acme" and tenant["memory_store_id"] is None
    assert client.get(f"/api/tenants/{tenant['id']}").json() == tenant
    assert client.get("/api/tenants").json() == [tenant]


def test_tenant_validation_and_not_found(client):
    assert client.post("/api/tenants", json={"name": "", "offering_summary": "x"}).status_code == 422
    assert client.post("/api/tenants", json={"name": "A", "offering_summary": "x",
                                             "default_assets": ["poster"]}).status_code == 422
    missing = client.get("/api/tenants/000000000000")
    assert missing.status_code == 404 and "detail" in missing.json()
    assert client.get("/api/tenants/..%2F..%2Fetc").status_code == 404


def test_upload_tenant_document(client, tenant):
    response = client.post(
        f"/api/tenants/{tenant['id']}/documents",
        files={"file": ("pricing sheet.md", b"# prices", "application/octet-stream")},
        data={"scope": "tenant", "account_slug": "ignored-for-tenant-scope"},
    )
    assert response.status_code == 201
    ref = response.json()
    assert ref["filename"] == "pricing_sheet.md" and ref["media_type"] == "text/markdown"
    assert ref["size_bytes"] == 8 and ref["scope"] == "tenant" and ref["account_slug"] is None
    assert client.get(f"/api/tenants/{tenant['id']}").json()["documents"] == [ref]


def test_upload_account_document_keeps_slug(client, tenant):
    response = client.post(
        f"/api/tenants/{tenant['id']}/documents", files={"file": ("a.txt", b"x")},
        data={"scope": "account", "account_slug": "globex"})
    assert response.status_code == 201 and response.json()["account_slug"] == "globex"


@pytest.mark.parametrize("data", [
    {"scope": "account"},
    {"scope": "account", "account_slug": "Bad Slug"},
    {"scope": "everyone"},
    {},
])
def test_upload_validation_errors(client, tenant, data):
    response = client.post(f"/api/tenants/{tenant['id']}/documents", files={"file": ("a.txt", b"x")},
                           data=data)
    assert response.status_code == 422


def test_upload_rejects_unsupported_type_with_415(client, tenant):
    response = client.post(f"/api/tenants/{tenant['id']}/documents",
                           files={"file": ("run.exe", b"MZ", "application/pdf")}, data={"scope": "tenant"})
    assert response.status_code == 415


def test_upload_over_limit_is_413(client, tenant, monkeypatch):
    monkeypatch.setattr("memoria.api.MAX_DOCUMENT_BYTES", 10)
    ok = client.post(f"/api/tenants/{tenant['id']}/documents", files={"file": ("a.txt", b"x" * 10)},
                     data={"scope": "tenant"})
    too_big = client.post(f"/api/tenants/{tenant['id']}/documents", files={"file": ("a.txt", b"x" * 11)},
                          data={"scope": "tenant"})
    assert (ok.status_code, too_big.status_code) == (201, 413)
    assert len(client.get(f"/api/tenants/{tenant['id']}").json()["documents"]) == 1


def test_upload_to_unknown_tenant_is_404(client):
    response = client.post("/api/tenants/000000000000/documents", files={"file": ("a.txt", b"x")},
                           data={"scope": "tenant"})
    assert response.status_code == 404


def test_create_session_ensures_memory_store_and_loads_snapshot(client, tenant, doubles):
    doubles.memory.files.update({"/accounts/globex/strategy.md": "old plan"})
    response = client.post("/api/sessions", json={
        "tenant_id": tenant["id"], "account_slug": "globex", "rep_slug": "dana"})
    assert response.status_code == 201
    created = response.json()
    assert created["phase"] == "interview" and created["turns"] == []
    assert created["memory_snapshot"] == {"/accounts/globex/strategy.md": "old plan"}
    assert all(slot["status"] == "open" for slot in created["board"]["slots"].values())
    assert doubles.memory.ensured == [(tenant["id"], "Acme")]
    stored_tenant = client.get(f"/api/tenants/{tenant['id']}").json()
    assert stored_tenant["memory_store_id"] == f"store-{tenant['id']}"
    assert client.get(f"/api/sessions/{created['id']}").json() == created


def test_second_session_reuses_the_tenants_store(client, tenant, doubles):
    body = {"tenant_id": tenant["id"], "account_slug": "globex", "rep_slug": "dana"}
    client.post("/api/sessions", json=body)
    client.post("/api/sessions", json=body)
    assert len(doubles.memory.ensured) == 1


@pytest.mark.parametrize("body", [
    {"account_slug": "globex", "rep_slug": "dana"},
    {"tenant_id": "x", "account_slug": "Globex Inc", "rep_slug": "dana"},
    {"tenant_id": "x", "account_slug": "globex", "rep_slug": "-dana"},
])
def test_create_session_validation(client, body):
    assert client.post("/api/sessions", json=body).status_code == 422


def test_create_session_for_unknown_tenant_is_404(client):
    response = client.post("/api/sessions", json={
        "tenant_id": "000000000000", "account_slug": "globex", "rep_slug": "dana"})
    assert response.status_code == 404


def test_session_and_assets_not_found(client):
    assert client.get("/api/sessions/000000000000").status_code == 404
    assert client.get("/api/sessions/000000000000/assets").status_code == 404


def test_assets_empty_before_a_build(client, session):
    assert client.get(f"/api/sessions/{session['id']}/assets").json() == []


@pytest.mark.parametrize("filename, media_type", [
    ("deck.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    ("doc.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ("doc.pdf", "application/pdf"),
    ("post.md", "text/markdown"),
    ("post.html", "text/html"),
    ("mail.eml", "message/rfc822"),
])
def test_rendered_files_are_served_with_their_media_type(client, session, settings, filename, media_type):
    directory = settings.data_dir / "sessions" / session["id"] / "rendered"
    directory.mkdir(parents=True)
    (directory / filename).write_bytes(b"content")
    response = client.get(f"/api/files/{session['id']}/{filename}")
    assert response.status_code == 200 and response.content == b"content"
    assert response.headers["content-type"].split(";")[0] == media_type


def test_files_outside_the_session_directory_are_404(client, session, settings):
    (settings.data_dir / "sessions" / session["id"] / "rendered").mkdir(parents=True)
    for path in [f"/api/files/{session['id']}/session.json", f"/api/files/{session['id']}/..%2Fsession.json",
                 f"/api/files/{session['id']}/%2e%2e%2f%2e%2e%2ftenants", "/api/files/..%2F/x",
                 f"/api/files/{session['id']}/nothing.pdf"]:
        assert client.get(path).status_code == 404, path


def test_tts_returns_wav_and_forwards_voice(client, doubles):
    response = client.post("/api/tts", json={"text": "Hello there", "voice": "af_bella"})
    assert response.status_code == 200 and response.headers["content-type"] == "audio/wav"
    assert response.content == b"RIFFwav"
    assert doubles.tts.calls == [("Hello there", "af_bella")]


@pytest.mark.parametrize("text", ["", "   ", "x" * 601])
def test_tts_rejects_empty_or_overlong_text(client, doubles, text):
    assert client.post("/api/tts", json={"text": text}).status_code == 400
    assert doubles.tts.calls == []


def test_tts_accepts_exactly_600_characters(client):
    assert client.post("/api/tts", json={"text": "x" * 600}).status_code == 200


def test_tts_backend_failure_is_a_502_and_is_logged(client, doubles, caplog):
    async def broken(text, voice=None):
        raise ConnectionError("kokoro down")

    doubles.tts.synthesize = broken
    with caplog.at_level(logging.ERROR, logger="memoria.api"):
        response = client.post("/api/tts", json={"text": "hi"})
    assert response.status_code == 502
    assert "kokoro down" in caplog.text


def test_cors_allows_configured_origin_only(client):
    allowed = client.get("/api/health", headers={"Origin": ORIGIN})
    denied = client.get("/api/health", headers={"Origin": "http://evil.example"})
    assert allowed.headers["access-control-allow-origin"] == ORIGIN
    assert "access-control-allow-origin" not in denied.headers


# WebSocket

def test_connecting_streams_the_opening_turn_and_persists_it(client, session):
    with client.websocket_connect(ws_url(session["id"])) as ws:
        events = collect_until(ws, "memoria_turn_done")
    assert [e["type"] for e in events] == ["memoria_delta", "memoria_sentence", "memoria_turn_done"]
    assert client.get(f"/api/sessions/{session['id']}").json()["turns"] == [
        {"speaker": "memoria", "text": "Who is the buyer?"}]


def test_reconnecting_does_not_repeat_the_opening(client, session):
    with client.websocket_connect(ws_url(session["id"])) as ws:
        collect_until(ws, "memoria_turn_done")
    with client.websocket_connect(ws_url(session["id"])) as ws:
        ws.send_json({"type": "rep_utterance", "text": "the CFO"})
        assert ws.receive_json()["type"] == "memoria_delta"
        assert collect_until(ws, "memoria_turn_done")


def test_utterance_events_arrive_in_engine_order_and_session_is_saved(client, session):
    with client.websocket_connect(ws_url(session["id"]), headers={"Origin": ORIGIN}) as ws:
        collect_until(ws, "memoria_turn_done")
        ws.send_json({"type": "rep_utterance", "text": "manual payroll"})
        events = collect_until(ws, "memoria_turn_done")
    assert [e["type"] for e in events] == ["memoria_delta", "slots_changed", "memoria_turn_done"]
    assert events[1]["board"]["slots"]["pain"]["value"] == "manual payroll"
    saved = client.get(f"/api/sessions/{session['id']}").json()
    assert [t["speaker"] for t in saved["turns"]] == ["memoria", "rep"]
    assert saved["board"]["slots"]["pain"]["status"] == "confirmed"


def test_engine_signalled_interview_complete_is_forwarded(client, session):
    with client.websocket_connect(ws_url(session["id"])) as ws:
        collect_until(ws, "memoria_turn_done")
        for text in ["one", "two"]:
            ws.send_json({"type": "rep_utterance", "text": text})
            events = collect_until(ws, "memoria_turn_done")
        assert ws.receive_json() == {"type": "interview_complete", "reason": "slots_filled"}
    assert events[-1]["type"] == "memoria_turn_done"


def test_end_interview_sends_rep_ended(client, session):
    with client.websocket_connect(ws_url(session["id"])) as ws:
        collect_until(ws, "memoria_turn_done")
        ws.send_json({"type": "end_interview"})
        assert ws.receive_json() == {"type": "interview_complete", "reason": "rep_ended"}


def test_invalid_messages_get_a_recoverable_error_and_the_socket_stays_usable(client, session):
    with client.websocket_connect(ws_url(session["id"])) as ws:
        collect_until(ws, "memoria_turn_done")
        for bad in ["not json", '{"type": "dance"}', '{"type": "rep_utterance", "text": ""}',
                    '{"type": "rep_utterance", "text": "' + "x" * 4001 + '"}']:
            ws.send_text(bad)
            error = ws.receive_json()
            assert error["type"] == "error" and error["recoverable"] is True
        ws.send_json({"type": "end_interview"})
        assert ws.receive_json()["type"] == "interview_complete"


def test_engine_failure_becomes_a_logged_recoverable_error(client, session, caplog):
    with client.websocket_connect(ws_url(session["id"])) as ws:
        collect_until(ws, "memoria_turn_done")
        with caplog.at_level(logging.ERROR, logger="memoria.api"):
            ws.send_json({"type": "rep_utterance", "text": "explode"})
            error = ws.receive_json()
        assert error == {"type": "error", "message": "interviewer exploded", "recoverable": True}
        assert "interviewer exploded" in caplog.text
        ws.send_json({"type": "rep_utterance", "text": "fine"})
        assert collect_until(ws, "memoria_turn_done")


def test_unknown_session_and_foreign_origin_are_refused(client, session):
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(ws_url("000000000000")):
        pass
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(
        ws_url(session["id"]), headers={"Origin": "http://evil.example"}
    ):
        pass


def build_events(ws):
    return collect_until(ws, "build_complete")


def test_start_build_streams_stages_in_chain_order_and_build_complete_is_last(client, session):
    with client.websocket_connect(ws_url(session["id"])) as ws:
        collect_until(ws, "memoria_turn_done")
        ws.send_json({"type": "start_build"})
        events = build_events(ws)
    stages = [(e["stage"]["stage_id"], e["stage"]["status"]) for e in events if e["type"] == "stage"]
    assert [s for s, status in stages if status == "running"] == [
        "deal_brief", "retrieval", "research", "personas", "strategy", "assets", "verifier",
        "memory_writer", "strategy_answer"]
    assert ("retrieval", "skipped") in stages
    assert events[-1]["type"] == "build_complete"
    types = [e["type"] for e in events]
    assert types.count("asset_ready") == 1 and types.count("memory_diff") == 1
    assert events[types.index("memory_diff")]["changes"][0]["change"] == "added"
    saved = client.get(f"/api/sessions/{session['id']}").json()
    assert saved["phase"] == "complete"
    assets = client.get(f"/api/sessions/{session['id']}/assets").json()
    assert assets[0]["asset_type"] == "deck"
    assert client.get(assets[0]["files"][0]["url"]).status_code == 200


def test_second_start_build_gets_an_error_and_does_not_rebuild(client, session, doubles):
    with client.websocket_connect(ws_url(session["id"])) as ws:
        collect_until(ws, "memoria_turn_done")
        ws.send_json({"type": "start_build"})
        build_events(ws)
        ws.send_json({"type": "start_build"})
        error = ws.receive_json()
    assert error["type"] == "error" and "already started" in error["message"]
    assert len(doubles.llm.calls("deal_brief")) == 1


def test_double_start_build_in_a_row_runs_the_build_once(client, session, doubles):
    with client.websocket_connect(ws_url(session["id"])) as ws:
        collect_until(ws, "memoria_turn_done")
        ws.send_json({"type": "start_build"})
        ws.send_json({"type": "start_build"})
        events = []
        while not any(e["type"] == "build_complete" for e in events):
            events.append(ws.receive_json())
    errors = [e for e in events if e["type"] == "error"]
    assert errors and "already started" in errors[0]["message"]
    assert len(doubles.llm.calls("deal_brief")) == 1


def test_socket_stays_responsive_while_the_build_runs(settings, render_recorder):
    gate = threading.Event()

    async def blocked(req):
        import asyncio
        await asyncio.to_thread(gate.wait, 5)
        return {"entries": []}

    doubles = Doubles(full_script(retrieval=blocked))
    ports = Ports(llm=doubles.llm, agents=doubles.agents, memory=doubles.memory, tts=doubles.tts)
    with TestClient(create_app(settings, ports)) as client:
        tenant = client.post("/api/tenants", json=PROFILE).json()
        client.post(f"/api/tenants/{tenant['id']}/documents", files={"file": ("a.md", b"x")},
                    data={"scope": "tenant"})
        session = client.post("/api/sessions", json={
            "tenant_id": tenant["id"], "account_slug": "globex", "rep_slug": "dana"}).json()
        with client.websocket_connect(ws_url(session["id"])) as ws:
            collect_until(ws, "memoria_turn_done")
            ws.send_json({"type": "start_build"})
            seen = []
            while not (seen and seen[-1].get("stage", {}).get("stage_id") == "retrieval"):
                seen.append(ws.receive_json())
            ws.send_json({"type": "rep_utterance", "text": "late word"})
            error = ws.receive_json()
            assert error["type"] == "error" and not gate.is_set()
            gate.set()
            assert build_events(ws)[-1]["type"] == "build_complete"


def test_build_failure_sends_a_non_recoverable_error_after_the_failed_stage(
    settings, render_recorder, caplog,
):
    doubles = Doubles(full_script(personas=RuntimeError("model overloaded")))
    ports = Ports(llm=doubles.llm, agents=doubles.agents, memory=doubles.memory, tts=doubles.tts)
    with TestClient(create_app(settings, ports)) as client:
        tenant = client.post("/api/tenants", json=PROFILE).json()
        session = client.post("/api/sessions", json={
            "tenant_id": tenant["id"], "account_slug": "globex", "rep_slug": "dana"}).json()
        with client.websocket_connect(ws_url(session["id"])) as ws, caplog.at_level(logging.ERROR):
            collect_until(ws, "memoria_turn_done")
            ws.send_json({"type": "start_build"})
            events = collect_until(ws, "error")
        failed = [e for e in events if e["type"] == "stage" and e["stage"]["status"] == "failed"]
        assert failed[0]["stage"]["detail"] == "model overloaded"
        assert events[-1] == {"type": "error", "message": "model overloaded", "recoverable": False}
        assert "build failed" in caplog.text
        assert client.get(f"/api/sessions/{session['id']}").json()["phase"] == "failed"


def test_build_uses_tenant_default_assets_and_campaign_assets_from_the_brief(
    settings, render_recorder,
):
    doubles = Doubles(full_script(
        deal_brief=brief(["deck", "blog"]),
        strategy={"asset_plan": [plan_entry("deck"), plan_entry("blog")]},
    ))
    ports = Ports(llm=doubles.llm, agents=doubles.agents, memory=doubles.memory, tts=doubles.tts)
    with TestClient(create_app(settings, ports)) as client:
        tenant = client.post("/api/tenants", json=PROFILE).json()
        session = client.post("/api/sessions", json={
            "tenant_id": tenant["id"], "account_slug": "globex", "rep_slug": "dana"}).json()
        with client.websocket_connect(ws_url(session["id"])) as ws:
            collect_until(ws, "memoria_turn_done")
            ws.send_json({"type": "start_build"})
            events = build_events(ws)
    assert sorted(e["asset"]["asset_type"] for e in events if e["type"] == "asset_ready") == ["blog", "deck"]


# Integration: needs the real fakes, interview engine and renderers from the other tracks.

@pytest.fixture
def fake_mode_client(tmp_path, monkeypatch):
    monkeypatch.undo()
    app = create_app(Settings(_env_file=None, mode="fake", data_dir=tmp_path))
    with TestClient(app) as test_client:
        yield test_client


def run_fake_session(client, tenant_id, utterances):
    session = client.post("/api/sessions", json={
        "tenant_id": tenant_id, "account_slug": "globex", "rep_slug": "dana"}).json()
    with client.websocket_connect(ws_url(session["id"]), headers={"Origin": ORIGIN}) as ws:
        events = collect_until(ws, "memoria_turn_done")
        for text in utterances:
            ws.send_json({"type": "rep_utterance", "text": text})
            events += collect_until(ws, "memoria_turn_done")
        if not any(e["type"] == "interview_complete" for e in events):
            events += collect_until(ws, "interview_complete")
        ws.send_json({"type": "start_build"})
        events += build_events(ws)
    return session, events


def test_full_session_flow_fake_mode(fake_mode_client):
    """Integration: real fakes, interview engine and renderers, over REST and the WebSocket."""
    client = fake_mode_client
    tenant = client.post("/api/tenants", json=PROFILE).json()
    upload = client.post(f"/api/tenants/{tenant['id']}/documents",
                         files={"file": ("facts.md", b"# Facts\nPayroll runs in minutes.")},
                         data={"scope": "account", "account_slug": "globex"})
    assert upload.status_code == 201

    utterances = [f"answer number {n}" for n in range(1, 12)]  # one per priority slot
    first, events = run_fake_session(client, tenant["id"], utterances)

    types = [e["type"] for e in events]
    assert "interview_complete" in types and types[-1] == "build_complete"
    assert types.index("interview_complete") < types.index("stage")
    stage_ids = [e["stage"]["stage_id"] for e in events if e["type"] == "stage"
                 and e["stage"]["status"] == "running"]
    assert stage_ids == ["deal_brief", "retrieval", "research", "personas", "strategy", "assets",
                         "verifier", "memory_writer", "strategy_answer"]
    assert not any(e["type"] == "error" for e in events)
    assert any(e["type"] == "strategy_answer" for e in events)

    saved = client.get(f"/api/sessions/{first['id']}").json()
    assert saved["phase"] == "complete" and saved["strategy_answer"]
    assert {c["change"] for c in saved["memory_diff"]} == {"added"}
    assets = client.get(f"/api/sessions/{first['id']}/assets").json()
    assert assets and all(a["verdict"] == "pass" and a["files"] for a in assets)
    for asset in assets:
        for rendered in asset["files"]:
            served = client.get(rendered["url"])
            assert served.status_code == 200 and len(served.content) == rendered["size_bytes"]

    second, second_events = run_fake_session(client, tenant["id"], utterances)
    second_saved = client.get(f"/api/sessions/{second['id']}").json()
    assert second_saved["memory_snapshot"]
    assert {c["change"] for c in second_saved["memory_diff"]} == {"modified"}
    assert second_saved["strategy_answer"].startswith("Since our last session")
    assert second_events[-1]["type"] == "build_complete"
