"""Inline markup shared by every renderer.

Asset text is parsed once into flat runs. Each output format maps runs to its
own markup and escapes the text itself, so nothing here produces markup.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

RunKind = Literal["text", "marker", "cite", "missing", "placeholder"]

_SAFE_URL = re.compile(r"^(https?://|mailto:)", re.IGNORECASE)

_TOKEN = re.compile(
    r"(?P<placeholder>\[PLACEHOLDER:[^\]]*\])"
    r"|(?P<marker>\[E(?P<marker_id>\d+)\])"
    r"|(?P<link>\[(?P<link_text>[^\]]+)\]\((?P<url>[^)\s]+)\))"
    r"|(?P<bold>\*\*(?P<bold_text>.+?)\*\*)"
    r"|(?P<italic>\*(?P<italic_text>[^*\s](?:[^*]*[^*\s])?)\*)"
)

MARKER = re.compile(r"\[E(\d+)\]")


@dataclass(frozen=True)
class Run:
    """A span of text with uniform formatting.

    kind "marker" carries the raw evidence ID ("E4") until Citations resolves
    it to a numbered "cite" run or a visible "missing" run.
    """

    text: str
    bold: bool = False
    italic: bool = False
    href: str | None = None
    kind: RunKind = "text"


def parse_inline(
    text: str, *, bold: bool = False, italic: bool = False, href: str | None = None
) -> list[Run]:
    runs: list[Run] = []
    position = 0

    def plain(chunk: str) -> None:
        if chunk:
            runs.append(Run(chunk, bold, italic, href))

    for match in _TOKEN.finditer(text):
        plain(text[position:match.start()])
        position = match.end()
        if match["placeholder"]:
            runs.append(Run(match["placeholder"], bold, italic, href, "placeholder"))
        elif match["marker"]:
            runs.append(Run(f"E{match['marker_id']}", kind="marker"))
        elif match["link"]:
            if _SAFE_URL.match(match["url"]):
                runs.extend(parse_inline(match["link_text"], bold=bold, italic=italic, href=match["url"]))
            else:
                plain(match["link"])
        elif match["bold"]:
            runs.extend(parse_inline(match["bold_text"], bold=True, italic=italic, href=href))
        else:
            runs.extend(parse_inline(match["italic_text"], bold=bold, italic=True, href=href))
    plain(text[position:])
    return runs
