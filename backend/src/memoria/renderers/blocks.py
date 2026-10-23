"""Block-level parsing of the supported body_markdown subset."""

from __future__ import annotations

import re
from dataclasses import dataclass

from memoria.renderers.inline import Run, parse_inline

_HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*#*\s*$")
_BULLET = re.compile(r"^\s*[-*+]\s+(.*)$")
_NUMBERED = re.compile(r"^\s*\d+[.)]\s+(.*)$")


@dataclass(frozen=True)
class Heading:
    level: int
    runs: list[Run]


@dataclass(frozen=True)
class Paragraph:
    runs: list[Run]


@dataclass(frozen=True)
class ListBlock:
    ordered: bool
    items: list[list[Run]]


Block = Heading | Paragraph | ListBlock


def parse_blocks(markdown: str, *, shift: int = 0) -> list[Block]:
    """Parse headings (#-###), paragraphs and flat lists; other syntax stays plain text.

    shift raises every heading level so body headings nest under the
    document's own title and section headings.
    """
    blocks: list[Block] = []
    paragraph: list[str] = []
    items: list[list[Run]] = []
    ordered = False

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(Paragraph(parse_inline(" ".join(paragraph))))
            paragraph.clear()

    def flush_list() -> None:
        if items:
            blocks.append(ListBlock(ordered, list(items)))
            items.clear()

    for raw in markdown.splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush_paragraph()
            flush_list()
            continue
        if heading := _HEADING.match(line):
            flush_paragraph()
            flush_list()
            blocks.append(Heading(len(heading[1]) + shift, parse_inline(heading[2])))
            continue
        bullet, numbered = _BULLET.match(line), _NUMBERED.match(line)
        if bullet or numbered:
            flush_paragraph()
            kind_is_ordered = numbered is not None and bullet is None
            if items and kind_is_ordered != ordered:
                flush_list()
            ordered = kind_is_ordered
            items.append(parse_inline((bullet or numbered)[1]))
            continue
        flush_list()
        paragraph.append(line.strip())
    flush_paragraph()
    flush_list()
    return blocks
