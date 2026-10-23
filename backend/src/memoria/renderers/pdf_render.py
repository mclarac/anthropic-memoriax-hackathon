"""PDF output via reportlab platypus."""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer

from memoria.renderers.blocks import Heading, ListBlock
from memoria.renderers.blocks import Paragraph as ParagraphBlock
from memoria.renderers.inline import Run
from memoria.renderers.longform import LongForm

_MAX_HEADING = 6


def runs_to_markup(runs: list[Run]) -> str:
    """reportlab parses Paragraph text as XML, so every character is escaped here."""
    return "".join(_run_to_markup(run) for run in runs)


def _run_to_markup(run: Run) -> str:
    if run.kind == "cite":
        return f"<super>[{escape(run.text)}]</super>"
    text = escape(run.text)
    if run.kind == "missing":
        return f'<font color="#b00020"><b>{text}</b></font>'
    if run.italic:
        text = f"<i>{text}</i>"
    if run.bold or run.kind == "placeholder":
        text = f"<b>{text}</b>"
    if run.href:
        text = f'<a href={quoteattr(run.href)} color="#0b5cad">{text}</a>'
    return text


def render_pdf(longform: LongForm, path: Path) -> None:
    styles = getSampleStyleSheet()
    flowables: list = [Paragraph(escape(longform.title), styles["Title"]), Spacer(1, 6)]
    for block in longform.blocks:
        if isinstance(block, Heading):
            style = styles[f"Heading{min(block.level, _MAX_HEADING)}"]
            flowables.append(Paragraph(runs_to_markup(block.runs), style))
        elif isinstance(block, ListBlock):
            items = [ListItem(Paragraph(runs_to_markup(item), styles["BodyText"])) for item in block.items]
            flowables.append(ListFlowable(items, bulletType="1" if block.ordered else "bullet"))
        elif isinstance(block, ParagraphBlock):
            flowables.append(Paragraph(runs_to_markup(block.runs), styles["BodyText"]))
    # Uncompressed streams keep the text extractable by simple tools and tests.
    SimpleDocTemplate(str(path), pagesize=LETTER, title=longform.title, pageCompression=0).build(flowables)
