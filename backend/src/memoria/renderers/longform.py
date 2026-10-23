"""Document and whitepaper content assembled into blocks shared by the docx and PDF writers."""

from __future__ import annotations

from dataclasses import dataclass

from memoria.renderers.blocks import Block, Heading, Paragraph, parse_blocks
from memoria.renderers.citations import Citations
from memoria.renderers.inline import Run


@dataclass(frozen=True)
class LongForm:
    title: str
    blocks: list[Block]


def build_longform(asset_type: str, content: dict, ledger: list[dict]) -> LongForm:
    """Section headings are level 1, so body markdown headings start at level 2."""
    citations = Citations(ledger)
    blocks: list[Block] = []
    if asset_type == "whitepaper":
        blocks.append(Heading(1, [Run("Executive summary")]))
        blocks.extend(citations.resolve_blocks(parse_blocks(content["executive_summary"], shift=1)))
    for section in content["sections"]:
        blocks.append(Heading(1, [Run(section["heading"])]))
        blocks.extend(citations.resolve_blocks(parse_blocks(section["body_markdown"], shift=1)))
    references = citations.references()
    if references:
        blocks.append(Heading(1, [Run("References")]))
        blocks.extend(
            Paragraph([Run(f"[{number}] {citations.reference_text(entry)}")]) for number, entry in references
        )
    return LongForm(content["title"], blocks)
