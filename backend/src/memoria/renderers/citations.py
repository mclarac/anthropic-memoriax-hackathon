"""Evidence markers resolved against the ledger."""

from __future__ import annotations

from dataclasses import replace

from memoria.renderers.blocks import Block, ListBlock
from memoria.renderers.inline import Run


def missing_evidence_text(evidence_id: str) -> str:
    return f"[{evidence_id}: missing evidence]"


class Citations:
    """Numbers each cited evidence ID in order of first use, across one document."""

    def __init__(self, ledger: list[dict]):
        self._entries = {entry["id"]: entry for entry in ledger}
        self._numbers: dict[str, int] = {}

    def resolve(self, runs: list[Run]) -> list[Run]:
        resolved: list[Run] = []
        for run in runs:
            if run.kind != "marker":
                resolved.append(run)
            elif run.text in self._entries:
                number = self._numbers.setdefault(run.text, len(self._numbers) + 1)
                resolved.append(Run(str(number), kind="cite"))
            else:
                resolved.append(self._missing(run))
        return resolved

    def drop_known(self, runs: list[Run]) -> list[Run]:
        """Remove markers that resolve, for outputs that list evidence separately."""
        return [
            self._missing(run) if run.kind == "marker" else run
            for run in runs
            if run.kind != "marker" or run.text not in self._entries
        ]

    def resolve_blocks(self, blocks: list[Block]) -> list[Block]:
        resolved: list[Block] = []
        for block in blocks:
            if isinstance(block, ListBlock):
                resolved.append(replace(block, items=[self.resolve(item) for item in block.items]))
            else:
                resolved.append(replace(block, runs=self.resolve(block.runs)))
        return resolved

    def references(self) -> list[tuple[int, dict]]:
        by_number = sorted((number, evidence_id) for evidence_id, number in self._numbers.items())
        return [(number, self._entries[evidence_id]) for number, evidence_id in by_number]

    def has(self, evidence_id: str) -> bool:
        return evidence_id in self._entries

    def entry(self, evidence_id: str) -> dict:
        return self._entries[evidence_id]

    @staticmethod
    def reference_text(entry: dict) -> str:
        date = entry.get("source_date") or "undated"
        return f"{entry['claim']} Source: {entry['source']} ({date})"

    @staticmethod
    def _missing(run: Run) -> Run:
        return Run(missing_evidence_text(run.text), bold=True, kind="missing")

