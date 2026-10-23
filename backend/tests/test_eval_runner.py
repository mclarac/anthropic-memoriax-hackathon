import asyncio
import json

import pytest

from memoria.eval.checks import CheckResult
from memoria.eval.runner import Task, run_eval


def always(name: str, passed: bool):
    def check(outputs):
        return CheckResult(name, passed, "d")

    return check


def flag_check(outputs):
    return CheckResult("flag", outputs["ok"], f"ok={outputs['ok']}")


def task(*checks, tenant="tenant-a", round=2):
    return Task(tenant=tenant, round=round, checks=list(checks))


async def test_rate_pass_at_k_and_pass_hat_k_for_mixed_trials():
    results_by_call = iter([True, False, True, True, False])

    async def agent(t):
        return {"ok": next(results_by_call)}

    out = await run_eval(agent, [task(flag_check)], trials=5, concurrency=1)
    t = out["tasks"][0]
    assert (t["passed"], t["completed"], t["errored"]) == (3, 5, 0)
    assert t["rate"] == pytest.approx(0.6)
    assert t["pass_at_k"] is True and t["pass_hat_k"] is False


async def test_all_pass_gives_pass_hat_k():
    async def agent(t):
        return {"ok": True}

    out = await run_eval(agent, [task(flag_check)], trials=3)
    t = out["tasks"][0]
    assert t["rate"] == 1.0 and t["pass_at_k"] and t["pass_hat_k"]


async def test_none_pass_gives_neither():
    async def agent(t):
        return {"ok": False}

    t = (await run_eval(agent, [task(flag_check)], trials=3))["tasks"][0]
    assert t["rate"] == 0.0 and not t["pass_at_k"] and not t["pass_hat_k"]


async def test_task_trial_passes_only_if_every_check_passes():
    async def agent(t):
        return {}

    out = await run_eval(agent, [task(always("a", True), always("b", False))], trials=2)
    t = out["tasks"][0]
    assert t["passed"] == 0
    assert t["checks"] == {"a": {"passed": 2, "failed": 0}, "b": {"passed": 0, "failed": 2}}


async def test_agent_exceptions_are_errored_not_failed():
    calls = iter(range(4))

    async def agent(t):
        if next(calls) % 2:
            raise TimeoutError("api timed out")
        return {"ok": True}

    t = (await run_eval(agent, [task(flag_check)], trials=4, concurrency=1))["tasks"][0]
    assert (t["passed"], t["errored"], t["completed"]) == (2, 2, 2)
    assert t["rate"] == 1.0
    assert t["pass_at_k"] and not t["pass_hat_k"]
    assert t["errors"] == ["TimeoutError: api timed out"] * 2
    assert t["checks"]["flag"] == {"passed": 2, "failed": 0}


async def test_all_runs_errored_has_no_rate():
    async def agent(t):
        raise RuntimeError("boom")

    t = (await run_eval(agent, [task(flag_check)], trials=2))["tasks"][0]
    assert t["rate"] is None and not t["pass_at_k"] and not t["pass_hat_k"] and t["errored"] == 2


async def test_check_exception_is_an_errored_run():
    def broken(outputs):
        raise KeyError("strategy_after")

    async def agent(t):
        return {}

    t = (await run_eval(agent, [task(broken)], trials=1))["tasks"][0]
    assert t["errored"] == 1 and "KeyError" in t["errors"][0]


async def test_errored_check_result_is_an_errored_run():
    def judge_confused(outputs):
        return CheckResult("judge", False, "unparseable", errored=True)

    async def agent(t):
        return {}

    t = (await run_eval(agent, [task(judge_confused)], trials=1))["tasks"][0]
    assert t["errored"] == 1 and t["passed"] == 0


async def test_async_checks_are_awaited():
    async def slow_check(outputs):
        await asyncio.sleep(0)
        return CheckResult("slow", True, "d")

    async def agent(t):
        return {}

    assert (await run_eval(agent, [task(slow_check)], trials=1))["tasks"][0]["passed"] == 1


async def test_concurrency_is_bounded():
    running = peak = 0

    async def agent(t):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return {}

    await run_eval(
        agent, [task(always("a", True)), task(always("a", True), round=3)], trials=4, concurrency=2
    )
    assert peak == 2


async def test_cost_and_latency_averaged_when_reported():
    outputs = iter(
        [
            {"ok": True, "cost_usd": 0.10, "ttft_ms": 400, "ttc_ms": 9000},
            {"ok": True, "cost_usd": 0.20, "ttft_ms": 600, "ttc_ms": 11000},
        ]
    )

    async def agent(t):
        return next(outputs)

    t = (await run_eval(agent, [task(flag_check)], trials=2, concurrency=1))["tasks"][0]
    assert t["mean_cost_usd"] == pytest.approx(0.15)
    assert t["mean_ttft_ms"] == pytest.approx(500)
    assert t["mean_ttc_ms"] == pytest.approx(10000)


async def test_cost_and_latency_absent_when_not_reported():
    async def agent(t):
        return {"ok": True}

    t = (await run_eval(agent, [task(flag_check)], trials=2))["tasks"][0]
    assert t["mean_cost_usd"] is None and t["mean_ttft_ms"] is None and t["mean_ttc_ms"] is None


async def test_writes_results_json_and_returns_same_structure(tmp_path):
    async def agent(t):
        return {"ok": True}

    out_path = tmp_path / "nested" / "results.json"
    out = await run_eval(agent, [task(flag_check)], trials=2, out_path=out_path)
    assert json.loads(out_path.read_text()) == out
    assert out["trials"] == 2
    assert out["tasks"][0]["tenant"] == "tenant-a" and out["tasks"][0]["round"] == 2


async def test_runs_record_per_trial_check_details():
    async def agent(t):
        return {"ok": False}

    runs = (await run_eval(agent, [task(flag_check)], trials=1))["tasks"][0]["runs"]
    assert runs == [{"status": "failed", "checks": [{"name": "flag", "passed": False, "detail": "ok=False"}]}]


async def test_invalid_arguments_rejected():
    async def agent(t):
        return {}

    with pytest.raises(ValueError):
        await run_eval(agent, [], trials=0)
    with pytest.raises(ValueError):
        await run_eval(agent, [], trials=1, concurrency=0)
