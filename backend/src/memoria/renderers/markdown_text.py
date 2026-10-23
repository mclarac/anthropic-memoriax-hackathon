"""Evidence handling for outputs that keep authored markdown (blog .md, email .md and .eml)."""

from __future__ import annotations

from memoria.renderers.citations import Citations, missing_evidence_text
from memoria.renderers.inline import MARKER


def flag_missing_markers(text: str, citations: Citations) -> str:
    """Rewrite markers that are not in the ledger so a human sees them."""
    return MARKER.sub(
        lambda m: m[0] if citations.has(f"E{m[1]}") else missing_evidence_text(f"E{m[1]}"), text
    )


def cited_ids(texts: list[str], citations: Citations) -> list[str]:
    """Known evidence IDs in order of first appearance."""
    seen: dict[str, None] = {}
    for text in texts:
        for match in MARKER.finditer(text):
            evidence_id = f"E{match[1]}"
            if citations.has(evidence_id):
                seen.setdefault(evidence_id)
    return list(seen)


def references_markdown(ids: list[str], citations: Citations) -> str:
    if not ids:
        return ""
    lines = [f"- [{i}] {citations.reference_text(citations.entry(i))}" for i in ids]
    return "## References\n\n" + "\n".join(lines) + "\n"
