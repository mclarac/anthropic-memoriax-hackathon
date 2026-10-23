"""Eval runner: tasks x trials with bounded concurrency.

Definitions, per task over k trials:
- completed: trials that ran and were graded. errored: trials where the agent or a check raised,
  or a check could not be graded. Errored trials never count as failed checks.
- rate: passed / completed (None when nothing completed).
- pass@k: passed at least once. pass^k: every one of the k trials passed, so an errored trial
  breaks it.
A trial passes only if every check passes.

Agent outputs may include cost_usd, ttft_ms and ttc_ms; each is averaged over the trials that report it.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memoria.eval.checks import CheckResult

Outputs = dict[str, Any]
Check = Callable[[Outputs], CheckResult | Awaitable[CheckResult]]
AgentFn = Callable[["Task"], Awaitable[Outputs]]

_METRICS = {"mean_cost_usd": "cost_usd", "mean_ttft_ms": "ttft_ms", "mean_ttc_ms": "ttc_ms"}


@dataclass
class Task:
    tenant: str
    round: int
    checks: list[Check]


@dataclass
class _Trial:
    status: str  # passed | failed | errored
    checks: list[CheckResult]
    error: str | None
    outputs: Outputs


async def _grade(check: Check, outputs: Outputs) -> CheckResult:
    result = check(outputs)
    return await result if inspect.isawaitable(result) else result


async def _run_trial(agent_fn: AgentFn, task: Task) -> _Trial:
    try:
        outputs = await agent_fn(task)
        results = [await _grade(check, outputs) for check in task.checks]
    except Exception as exc:
        return _Trial("errored", [], f"{type(exc).__name__}: {exc}", {})
    ungradable = [r for r in results if r.errored]
    if ungradable:
        return _Trial("errored", [], f"{ungradable[0].name}: {ungradable[0].detail}", outputs)
    status = "passed" if all(r.passed for r in results) else "failed"
    return _Trial(status, results, None, outputs)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _summarize(task: Task, trials: list[_Trial]) -> dict[str, Any]:
    passed = sum(t.status == "passed" for t in trials)
    errored = sum(t.status == "errored" for t in trials)
    completed = len(trials) - errored
    checks: dict[str, dict[str, int]] = {}
    for trial in trials:
        for result in trial.checks:
            tally = checks.setdefault(result.name, {"passed": 0, "failed": 0})
            tally["passed" if result.passed else "failed"] += 1
    summary: dict[str, Any] = {
        "tenant": task.tenant,
        "round": task.round,
        "trials": len(trials),
        "completed": completed,
        "errored": errored,
        "passed": passed,
        "rate": passed / completed if completed else None,
        "pass_at_k": passed >= 1,
        "pass_hat_k": passed == len(trials),
        "checks": checks,
        "errors": [t.error for t in trials if t.error and t.status == "errored"],
    }
    for key, source in _METRICS.items():
        summary[key] = _mean([t.outputs[source] for t in trials if source in t.outputs])
    summary["runs"] = [
        {
            "status": t.status,
            "checks": [{"name": r.name, "passed": r.passed, "detail": r.detail} for r in t.checks],
            **({"error": t.error} if t.error else {}),
        }
        for t in trials
    ]
    return summary


async def run_eval(
    agent_fn: AgentFn,
    tasks: list[Task],
    trials: int = 5,
    concurrency: int = 2,
    out_path: str | Path | None = None,
) -> dict[str, Any]:
    if trials < 1:
        raise ValueError("trials must be at least 1")
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    gate = asyncio.Semaphore(concurrency)

    async def bounded(task: Task) -> _Trial:
        async with gate:
            return await _run_trial(agent_fn, task)

    per_task = await asyncio.gather(*(asyncio.gather(*(bounded(t) for _ in range(trials))) for t in tasks))
    results = {
        "trials": trials,
        "tasks": [_summarize(task, list(runs)) for task, runs in zip(tasks, per_task, strict=True)],
    }
    if out_path is not None:
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(results, indent=2))
    return results
