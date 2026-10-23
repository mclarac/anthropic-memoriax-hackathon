import json
from pathlib import Path

import pytest

import memoria.eval.__main__ as cli
from memoria.eval.dataset import load_datasets
from memoria.eval.runner import run_eval
from memoria.eval.tasks import build_tasks
from memoria.models import AssetRef, Slot, SlotBoard

ROOT = Path(__file__).resolve().parents[2] / "datasets"


@pytest.fixture(scope="module")
def datasets():
    return load_datasets(ROOT)


def good_round1(ds):
    board = SlotBoard()
    for name, value in ds.rounds[1].fact_sheet.items():
        if value is not None:
            board.slots[name] = Slot(value=value, status="confirmed")
    return {"board": board, "texts": ["a clean answer"]}


def good_round2(ds):
    exp = ds.rounds[2].expectations
    answer = "Since our last session: " + " ".join(
        exp.new_objection_keywords + exp.competitive_update_keywords
    )
    return {
        "answer": answer,
        "strategy_before": {"pitch_sequence": [{"order": 1, "segment": "A"}, {"order": 2, "segment": "B"}]},
        "strategy_after": {"pitch_sequence": [{"order": 1, "segment": "B"}, {"order": 2, "segment": "A"}]},
        "memory_snapshot": {f"/accounts/{ds.account_slug}/objections.md": "O1 superseded by O4"},
        "assets": [AssetRef(asset_type="deck", title="d", verdict="pass")],
        "texts": [answer],
    }


def test_one_task_per_tenant_and_round(datasets):
    tasks = build_tasks(datasets)
    assert [(t.tenant, t.round) for t in tasks] == [(d.slug, n) for d in datasets for n in (1, 2, 3)]


async def test_good_outputs_pass_every_task(datasets):
    by_key = {(d.slug, 1): good_round1(d) for d in datasets}
    by_key |= {(d.slug, 2): good_round2(d) for d in datasets}
    for d in datasets:
        flag = " ".join(d.rounds[3].expectations.conflict_keywords)
        by_key[(d.slug, 3)] = {"answer": f"These conflict: {flag}. Which is right?", "texts": [flag]}

    async def agent(task):
        return by_key[(task.tenant, task.round)]

    results = await run_eval(agent, build_tasks(datasets), trials=1)
    assert [t["passed"] for t in results["tasks"]] == [1] * 9, results["tasks"]


async def test_round_two_fails_when_agent_ignores_the_new_objection(datasets):
    ds = datasets[0]
    out = good_round2(ds)
    out["answer"] = "Since our last session: nothing notable."

    async def agent(task):
        return out

    results = await run_eval(
        agent, [t for t in build_tasks(datasets) if (t.tenant, t.round) == (ds.slug, 2)], trials=1
    )
    checks = results["tasks"][0]["checks"]
    assert checks["new_objection_present"]["failed"] == 1
    assert checks["competitive_update_used"]["failed"] == 1
    assert checks["leads_with_change"]["passed"] == 1


async def test_foreign_canary_in_output_fails_isolation_for_every_round(datasets):
    leaked = datasets[1].canary
    ds = datasets[0]
    out = good_round1(ds) | {"texts": [f"codename {leaked}"]}

    async def agent(task):
        return out

    task = next(t for t in build_tasks(datasets) if (t.tenant, t.round) == (ds.slug, 1))
    results = await run_eval(agent, [task], trials=1)
    assert results["tasks"][0]["checks"]["canary_absent"]["failed"] == 1


async def test_own_canary_in_output_is_not_a_leak(datasets):
    ds = datasets[0]
    out = good_round1(ds) | {"texts": [ds.canary]}

    async def agent(task):
        return out

    task = next(t for t in build_tasks(datasets) if (t.tenant, t.round) == (ds.slug, 1))
    assert (await run_eval(agent, [task], trials=1))["tasks"][0]["passed"] == 1


async def test_only_filter_still_checks_against_all_canaries(datasets):
    tasks = build_tasks(datasets, only=[datasets[0].slug])
    assert {t.tenant for t in tasks} == {datasets[0].slug}

    async def agent(task):
        return good_round1(datasets[0]) | {"texts": [datasets[2].canary]}

    results = await run_eval(agent, [t for t in tasks if t.round == 1], trials=1)
    assert results["tasks"][0]["checks"]["canary_absent"]["failed"] == 1


def test_parse_args_defaults_and_required_out():
    args = cli.parse_args(["--out", "results/x.json"])
    assert (args.trials, args.concurrency, args.dataset) == (5, 2, Path("../datasets"))
    with pytest.raises(SystemExit):
        cli.parse_args([])


def test_format_summary_lists_each_task_and_failed_checks():
    results = {
        "trials": 5,
        "tasks": [
            {
                "tenant": "tenant-a",
                "round": 2,
                "trials": 5,
                "passed": 3,
                "errored": 1,
                "rate": 0.75,
                "pass_at_k": True,
                "pass_hat_k": False,
                "mean_cost_usd": 0.1234,
                "mean_ttft_ms": None,
                "mean_ttc_ms": 9000.0,
                "checks": {"pitch_order_changed": {"passed": 3, "failed": 1}},
            },
        ],
    }
    text = cli.format_summary(results)
    lines = text.splitlines()
    assert lines[0].split()[:3] == ["tenant", "round", "pass"]
    assert "tenant-a" in lines[2] and "3/5" in lines[2] and "0.75" in lines[2] and "0.123" in lines[2]
    assert "failed checks: pitch_order_changed x1" in text


async def test_main_rejects_unknown_tenant(tmp_path, capsys):
    code = await cli.main(["--dataset", str(ROOT), "--out", str(tmp_path / "r.json"), "--tenant", "tenant-z"])
    assert code == 2 and "tenant-z" in capsys.readouterr().err


async def test_main_writes_results_and_prints_table(tmp_path, monkeypatch, capsys, datasets):
    async def fake_agent(task):
        return {"texts": [], "answer": "", "board": SlotBoard()}

    monkeypatch.setattr(cli, "build_agent_fn", lambda settings, datasets: fake_agent)
    out = tmp_path / "res" / "r.json"
    code = await cli.main(
        ["--dataset", str(ROOT), "--out", str(out), "--trials", "2", "--tenant", "tenant-a"]
    )
    assert code == 0
    data = json.loads(out.read_text())
    assert data["trials"] == 2 and {t["tenant"] for t in data["tasks"]} == {"tenant-a"}
    assert "tenant-a" in capsys.readouterr().out
