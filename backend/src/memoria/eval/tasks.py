"""Builds eval tasks from datasets.

The agent function returns a dict with these keys (a round only needs the keys its checks read):
  board            SlotBoard after the interview                      (round 1)
  answer           the strategy answer text                          (rounds 2 and 3)
  strategy_before  strategy artifact from the previous session       (round 2)
  strategy_after   strategy artifact from this session               (round 2)
  memory_snapshot  {path: content} after the memory writer ran       (round 2)
  assets           list[AssetRef]                                    (rounds 2 and 3)
  texts            every user-visible output string, for the canary check
It may also report cost_usd, ttft_ms and ttc_ms (see runner).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from memoria.eval import checks
from memoria.eval.dataset import TenantDataset
from memoria.eval.runner import Check, Task

# Round 3 names both the old and the new value when flagging, so require two hits.
CONFLICT_MIN_HITS = 2


def _canary(foreign: list[str]) -> Check:
    return lambda out: checks.canary_absent(out["texts"], foreign)


def _answer_check(fn: Callable[..., checks.CheckResult], *args: Any, **kwargs: Any) -> Check:
    return lambda out: fn(out["answer"], *args, **kwargs)


def build_tasks(
    datasets: list[TenantDataset], rounds: tuple[int, ...] = (1, 2, 3), only: list[str] | None = None
) -> list[Task]:
    """`only` limits which tenants get tasks. Every dataset still feeds the isolation check."""
    tasks: list[Task] = []
    for ds in datasets:
        if only and ds.slug not in only:
            continue
        foreign = [other.canary for other in datasets if other.slug != ds.slug]
        for number in rounds:
            rnd = ds.rounds[number]
            exp = rnd.expectations
            if number == 1:
                round_checks: list[Check] = [
                    lambda out, facts=rnd.fact_sheet: checks.slot_recall(out["board"], facts),
                    _canary(foreign),
                ]
            elif number == 2:
                round_checks = [
                    _answer_check(
                        checks.mentions_keywords, exp.new_objection_keywords, name="new_objection_present"
                    ),
                    _answer_check(
                        checks.mentions_keywords,
                        exp.competitive_update_keywords,
                        name="competitive_update_used",
                    ),
                    _answer_check(checks.leads_with_change),
                    lambda out: checks.pitch_order_changed(out["strategy_before"], out["strategy_after"]),
                    lambda out, slug=ds.account_slug: checks.objection_superseded(
                        out["memory_snapshot"], slug
                    ),
                    lambda out: checks.assets_verified(out["assets"]),
                    _canary(foreign),
                ]
            else:
                round_checks = [
                    _answer_check(
                        checks.mentions_keywords,
                        exp.conflict_keywords,
                        min_hits=CONFLICT_MIN_HITS,
                        name="conflict_flagged",
                    ),
                    _canary(foreign),
                ]
            tasks.append(Task(tenant=ds.slug, round=number, checks=round_checks))
    return tasks
