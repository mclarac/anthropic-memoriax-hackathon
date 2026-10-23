"""CLI: python -m memoria.eval --dataset ../datasets --trials 5 --out results/<name>.json"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

from memoria.config import Settings
from memoria.eval.agent import build_agent_fn
from memoria.eval.dataset import load_datasets
from memoria.eval.runner import run_eval
from memoria.eval.tasks import build_tasks


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m memoria.eval", description="Run the Memoria evaluation.")
    parser.add_argument(
        "--dataset", type=Path, default=Path("../datasets"), help="directory holding tenant-* datasets"
    )
    parser.add_argument("--trials", type=int, default=5, help="trials per task")
    parser.add_argument("--concurrency", type=int, default=2, help="trials running at once")
    parser.add_argument("--out", type=Path, required=True, help="results JSON path, e.g. results/run1.json")
    parser.add_argument(
        "--tenant", action="append", dest="tenants", help="limit to this tenant directory name; repeatable"
    )
    return parser.parse_args(argv)


def _fmt(value: float | None, spec: str) -> str:
    return "-" if value is None else format(value, spec)


def format_summary(results: dict[str, Any]) -> str:
    header = ["tenant", "round", "pass", "err", "rate", "pass@k", "pass^k", "cost", "ttft ms", "ttc ms"]
    rows = [header]
    for t in results["tasks"]:
        rows.append(
            [
                t["tenant"],
                str(t["round"]),
                f"{t['passed']}/{t['trials']}",
                str(t["errored"]),
                _fmt(t["rate"], ".2f"),
                "yes" if t["pass_at_k"] else "no",
                "yes" if t["pass_hat_k"] else "no",
                _fmt(t["mean_cost_usd"], ".3f"),
                _fmt(t["mean_ttft_ms"], ".0f"),
                _fmt(t["mean_ttc_ms"], ".0f"),
            ]
        )
    widths = [max(len(r[i]) for r in rows) for i in range(len(header))]
    lines = ["  ".join(cell.ljust(w) for cell, w in zip(r, widths, strict=True)).rstrip() for r in rows]
    lines.insert(1, "  ".join("-" * w for w in widths))
    failing = {name: c["failed"] for t in results["tasks"] for name, c in t["checks"].items() if c["failed"]}
    if failing:
        lines.append("")
        lines.append("failed checks: " + ", ".join(f"{n} x{c}" for n, c in sorted(failing.items())))
    return "\n".join(lines)


async def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    datasets = load_datasets(args.dataset)
    unknown = set(args.tenants or []) - {d.slug for d in datasets}
    if unknown:
        print(f"unknown tenant(s): {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2
    agent_fn = build_agent_fn(Settings(), datasets)
    results = await run_eval(
        agent_fn,
        build_tasks(datasets, only=args.tenants),
        trials=args.trials,
        concurrency=args.concurrency,
        out_path=args.out,
    )
    print(format_summary(results))
    print(f"\nresults written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
