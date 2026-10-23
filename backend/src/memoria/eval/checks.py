"""Deterministic checks. Pure functions over the agent's outputs; no model calls."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from memoria.models import AssetRef, SlotBoard

LEAD_PHRASE = "since our last session"


@dataclass(frozen=True)
class CheckResult:
    """errored marks a check that could not be graded (for example a malformed judge reply).

    It is distinct from a failed check: the runner records it as an errored run.
    """

    name: str
    passed: bool
    detail: str
    errored: bool = False


def slot_recall(board: SlotBoard, fact_sheet: Mapping[str, Any], threshold: float = 0.8) -> CheckResult:
    """Share of known fact-sheet slots the interview settled (confirmed, or the rep said unsure)."""
    expected = [name for name, value in fact_sheet.items() if value is not None]
    if not expected:
        return CheckResult("slot_recall", True, "no non-null slots in the fact sheet")
    missed = [
        name
        for name in expected
        if name not in board.slots or board.slots[name].status not in ("confirmed", "rep_unsure")
    ]
    recall = (len(expected) - len(missed)) / len(expected)
    detail = f"recall {recall:.2f} (threshold {threshold:.2f})"
    if missed:
        detail += f"; missed: {', '.join(missed)}"
    return CheckResult("slot_recall", recall >= threshold, detail)


def mentions_keywords(
    text: str, keywords: Iterable[str], min_hits: int = 1, name: str = "mentions_keywords"
) -> CheckResult:
    """Case-insensitive keyword presence. An empty keyword list fails: it would pass vacuously."""
    keywords = list(keywords)
    if not keywords:
        return CheckResult(name, False, "no keywords given")
    lowered = text.casefold()
    hits = [k for k in keywords if k.casefold() in lowered]
    detail = f"{len(hits)}/{len(keywords)} keywords found (need {min_hits})"
    if len(hits) < min_hits:
        detail += f"; missing: {', '.join(k for k in keywords if k not in hits)}"
    return CheckResult(name, len(hits) >= min_hits, detail)


def _pitch_titles(strategy: Mapping[str, Any]) -> list[str] | None:
    segments = strategy.get("pitch_sequence")
    if not segments:
        return None
    ordered = sorted(segments, key=lambda s: s.get("order", 0))
    return [" ".join(s["segment"].casefold().split()) for s in ordered]


def pitch_order_changed(strategy_before: Mapping[str, Any], strategy_after: Mapping[str, Any]) -> CheckResult:
    name = "pitch_order_changed"
    before, after = _pitch_titles(strategy_before), _pitch_titles(strategy_after)
    if before is None:
        return CheckResult(name, False, "strategy before has no pitch_sequence")
    if after is None:
        return CheckResult(name, False, "strategy after has no pitch_sequence")
    if before == after:
        return CheckResult(name, False, f"segment order unchanged: {' > '.join(after)}")
    return CheckResult(name, True, f"{' > '.join(before)}  ->  {' > '.join(after)}")


def objection_superseded(memory_snapshot: Mapping[str, str], account_slug: str) -> CheckResult:
    name = "objection_superseded"
    wanted = f"accounts/{account_slug}/objections.md"
    for path, content in memory_snapshot.items():
        if path.lstrip("/") == wanted:
            if "superseded" in content.casefold():
                return CheckResult(name, True, f"{wanted} marks an objection superseded")
            return CheckResult(name, False, f"{wanted} has no 'superseded' status")
    return CheckResult(name, False, f"{wanted} not found in memory snapshot")


def canary_absent(texts: Iterable[str], foreign_canaries: Iterable[str]) -> CheckResult:
    """Isolation check: no other tenant's canary string appears in any output text."""
    texts = list(texts)
    leaked = sorted({c for c in foreign_canaries if any(c in t for t in texts)})
    if leaked:
        return CheckResult("canary_absent", False, f"leaked: {', '.join(leaked)}")
    return CheckResult("canary_absent", True, f"checked {len(texts)} texts")


def assets_verified(assets: list[AssetRef]) -> CheckResult:
    if not assets:
        return CheckResult("assets_verified", False, "no assets were produced")
    flagged = [a.title for a in assets if a.verdict != "pass"]
    if flagged:
        return CheckResult(
            "assets_verified", False, f"{len(flagged)} need human review: {', '.join(flagged)}"
        )
    return CheckResult("assets_verified", True, f"{len(assets)} assets verified")


def leads_with_change(answer: str) -> CheckResult:
    passed = answer.lstrip().casefold().startswith(LEAD_PHRASE)
    snippet = answer.strip()[:60]
    return CheckResult("leads_with_change", passed, f"answer begins: {snippet!r}")
