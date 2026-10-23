import json
from pathlib import Path

import pytest

from memoria import cli
from memoria.app import build_ports
from memoria.config import Settings
from memoria.storage import Storage

PROFILE = {
    "name": "Pellucid", "offering_summary": "Telemetry pipeline", "brand_voice": "plain",
    "account_slug": "northwind", "rep_slug": "sam",
}
# Fake mode completes the interview once every priority slot is filled: eleven answers.
UTTERANCES = [f"answer {n}" for n in range(1, 12)]


def write_dataset(root, rounds=(1, 2), utterances=UTTERANCES):
    dataset = root / "tenant-x"
    dataset.mkdir()
    (dataset / "profile.json").write_text(json.dumps(PROFILE))
    for n in rounds:
        round_dir = dataset / f"round{n}"
        (round_dir / "documents").mkdir(parents=True)
        (round_dir / "rep_utterances.json").write_text(json.dumps(utterances))
        (round_dir / "documents" / f"notes-{n}.md").write_text(f"# Round {n} notes\nFacts.")
    return dataset


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("MEMORIA_MODE", "fake")
    monkeypatch.setenv("MEMORIA_DATA_DIR", str(data))
    return data


def test_card_d_writes_report_with_question_answer_assets_and_memory_diff(tmp_path, fake_env, capsys):
    """Integration: real fakes, interview engine and renderers, in fake mode."""
    dataset = write_dataset(tmp_path)
    out = tmp_path / "out"

    cli.main(["card-d", "--dataset", str(dataset), "--round", "1", "--out", str(out)])

    report = (out / "session1.txt").read_text()
    assert "Tomorrow's call is the final pitch. What's our strategy?" in report
    assert "Strategy answer:\nFirst session for northwind" in report
    assert "[pass]" in report
    rendered_paths = [line.strip() for line in report.splitlines() if line.startswith("    ")]
    assert rendered_paths and all(p.startswith(str(fake_env)) for p in rendered_paths)
    assert all(Path(p).is_file() for p in rendered_paths)
    assert "- added /accounts/northwind/objections.md" in report
    assert "strategy_answer: done" in capsys.readouterr().out


def test_round_two_reuses_the_tenant_created_in_round_one(tmp_path, fake_env):
    """Integration: two CLI invocations share one tenant through <data_dir>/datasets.json."""
    dataset = write_dataset(tmp_path)
    out = tmp_path / "out"
    cli.main(["card-d", "--dataset", str(dataset), "--round", "1", "--out", str(out)])
    cli.main(["card-d", "--dataset", str(dataset), "--round", "2", "--out", str(out)])

    storage = Storage(fake_env)
    tenants = storage.list_tenants()
    assert len(tenants) == 1
    assert json.loads((fake_env / "datasets.json").read_text()) == {"tenant-x": tenants[0].id}
    assert [d.filename for d in tenants[0].documents] == ["notes-1.md", "notes-2.md"]
    assert all(d.scope == "account" and d.account_slug == "northwind" for d in tenants[0].documents)
    assert (out / "session1.txt").exists() and (out / "session2.txt").exists()


async def test_second_round_in_one_process_modifies_memory_and_leads_with_what_changed(tmp_path):
    """Integration: shared fake ports across rounds, as the eval runner would use them."""
    settings = Settings(_env_file=None, mode="fake", data_dir=tmp_path / "data")
    ports = build_ports(settings)
    dataset = write_dataset(tmp_path)
    await cli.run_card_d(settings, ports, dataset, 1, tmp_path / "out")
    second = await cli.run_card_d(settings, ports, dataset, 2, tmp_path / "out")

    report = second.read_text()
    assert "Since our last session" in report
    assert "- modified /accounts/northwind/objections.md" in report


async def test_interview_stops_feeding_utterances_once_it_is_complete(tmp_path):
    settings = Settings(_env_file=None, mode="fake", data_dir=tmp_path / "data")
    dataset = write_dataset(tmp_path, rounds=(1,), utterances=UTTERANCES + ["never used"] * 4)
    await cli.run_card_d(settings, build_ports(settings), dataset, 1, tmp_path / "out")

    session_dir = next((tmp_path / "data" / "sessions").iterdir())
    turns = json.loads((session_dir / "session.json").read_text())["turns"]
    assert [t["text"] for t in turns if t["speaker"] == "rep"] == UTTERANCES


async def test_a_round_with_too_few_utterances_still_builds(tmp_path):
    settings = Settings(_env_file=None, mode="fake", data_dir=tmp_path / "data")
    dataset = write_dataset(tmp_path, rounds=(1,), utterances=UTTERANCES[:3])
    report = await cli.run_card_d(settings, build_ports(settings), dataset, 1, tmp_path / "out")
    assert "Strategy answer:" in report.read_text()


def test_missing_round_files_exit_with_a_message_instead_of_a_traceback(tmp_path, fake_env, capsys):
    dataset = write_dataset(tmp_path, rounds=(1,))
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["card-d", "--dataset", str(dataset), "--round", "2", "--out", str(tmp_path / "out")])
    assert exit_info.value.code == 2
    err = capsys.readouterr().err
    assert "round2" in err and "rep_utterances.json" in err


@pytest.mark.parametrize("profile, message", [
    ("not json", "not valid JSON"),
    ('{"name": "X", "offering_summary": "y"}', "account_slug"),
])
def test_bad_profile_is_a_dataset_error(tmp_path, fake_env, capsys, profile, message):
    dataset = write_dataset(tmp_path, rounds=(1,))
    (dataset / "profile.json").write_text(profile)
    with pytest.raises(SystemExit):
        cli.main(["card-d", "--dataset", str(dataset), "--round", "1", "--out", str(tmp_path / "out")])
    assert message in capsys.readouterr().err


def test_unsupported_round_document_is_rejected(tmp_path, fake_env, capsys):
    dataset = write_dataset(tmp_path, rounds=(1,))
    (dataset / "round1" / "documents" / "payload.exe").write_bytes(b"MZ")
    with pytest.raises(SystemExit):
        cli.main(["card-d", "--dataset", str(dataset), "--round", "1", "--out", str(tmp_path / "out")])
    assert "payload.exe" in capsys.readouterr().err


def test_utterances_must_be_a_list_of_strings(tmp_path, fake_env, capsys):
    dataset = write_dataset(tmp_path, rounds=(1,))
    (dataset / "round1" / "rep_utterances.json").write_text('{"a": 1}')
    with pytest.raises(SystemExit):
        cli.main(["card-d", "--dataset", str(dataset), "--round", "1", "--out", str(tmp_path / "out")])
    assert "list of strings" in capsys.readouterr().err


def test_serve_starts_uvicorn_on_all_interfaces_port_8000(monkeypatch):
    calls = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    cli.main(["serve"])
    assert calls == [(("memoria.app:create_app",), {"factory": True, "host": "0.0.0.0", "port": 8000})]


def test_a_command_is_required():
    with pytest.raises(SystemExit):
        cli.main([])
