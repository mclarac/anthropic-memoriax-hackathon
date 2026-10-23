"""Blog output: authored markdown plus a standalone HTML5 page."""

from __future__ import annotations

from html import escape
from pathlib import Path

from memoria.renderers.blocks import Block, Heading, ListBlock, parse_blocks
from memoria.renderers.citations import Citations
from memoria.renderers.inline import Run, parse_inline
from memoria.renderers.markdown_text import cited_ids, flag_missing_markers, references_markdown

_STYLE = """\
body{margin:0;background:#fbfaf7;color:#1f1f1f;font:18px/1.65 Georgia,"Times New Roman",serif}
article{max-width:42rem;margin:0 auto;padding:3rem 1.25rem 4rem}
h1{font-size:2.2rem;line-height:1.2;margin:0 0 1.5rem}
h2,h3,h4{line-height:1.3;margin:2.2rem 0 .6rem}
p,ul,ol{margin:0 0 1.1rem}
a{color:#0b5cad}
sup a{text-decoration:none;font-size:.8em}
mark.placeholder{background:#fff1a8;padding:0 .2em;font-weight:bold}
.missing-evidence{color:#b00020;font-weight:bold}
.cta{margin:2.5rem 0;padding:1rem 1.25rem;border-left:4px solid #0b5cad;background:#eef3f9;font-weight:bold}
.references{margin-top:3rem;border-top:1px solid #d8d4ca;font-size:.85rem;color:#444}
.references h2{font-size:1.1rem}
"""


def runs_to_html(runs: list[Run]) -> str:
    return "".join(_run_to_html(run) for run in runs)


def _run_to_html(run: Run) -> str:
    text = escape(run.text)
    if run.kind == "cite":
        return f'<sup><a href="#ref-{run.text}">[{text}]</a></sup>'
    if run.kind == "missing":
        return f'<span class="missing-evidence">{text}</span>'
    if run.kind == "placeholder":
        text = f'<mark class="placeholder">{text}</mark>'
    if run.italic:
        text = f"<em>{text}</em>"
    if run.bold and run.kind != "placeholder":
        text = f"<strong>{text}</strong>"
    if run.href:
        text = f'<a href="{escape(run.href)}">{text}</a>'
    return text


def blocks_to_html(blocks: list[Block]) -> str:
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, Heading):
            level = min(block.level, 6)
            parts.append(f"<h{level}>{runs_to_html(block.runs)}</h{level}>")
        elif isinstance(block, ListBlock):
            tag = "ol" if block.ordered else "ul"
            items = "".join(f"<li>{runs_to_html(item)}</li>" for item in block.items)
            parts.append(f"<{tag}>{items}</{tag}>")
        else:
            parts.append(f"<p>{runs_to_html(block.runs)}</p>")
    return "\n".join(parts)


def render_blog(content: dict, ledger: list[dict], out_dir: Path, basename: str) -> list[Path]:
    markdown_path = out_dir / f"{basename}.md"
    html_path = out_dir / f"{basename}.html"
    markdown_path.write_text(_markdown(content, Citations(ledger)), encoding="utf-8")
    html_path.write_text(_html(content, Citations(ledger)), encoding="utf-8")
    return [markdown_path, html_path]


def _markdown(content: dict, citations: Citations) -> str:
    body = flag_missing_markers(content["body_markdown"].strip(), citations)
    cta = flag_missing_markers(content["cta"].strip(), citations)
    parts = [f"# {content['title']}", body, f"**{cta}**"]
    ids = cited_ids([content["body_markdown"], content["cta"]], citations)
    references = references_markdown(ids, citations)
    if references:
        parts.append(references.rstrip())
    return "\n\n".join(parts) + "\n"


def _html(content: dict, citations: Citations) -> str:
    body = blocks_to_html(citations.resolve_blocks(parse_blocks(content["body_markdown"], shift=1)))
    cta = runs_to_html(citations.resolve(parse_inline(content["cta"])))
    references = citations.references()
    footer = ""
    if references:
        items = "\n".join(
            f'<li id="ref-{number}">{escape(citations.reference_text(entry))}</li>'
            for number, entry in references
        )
        footer = (
            '<footer><section class="references"><h2>References</h2>\n'
            f"<ol>\n{items}\n</ol></section></footer>"
        )
    title = escape(content["title"])
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{escape(content["meta_description"])}">
<style>
{_STYLE}</style>
</head>
<body>
<article>
<header><h1>{title}</h1></header>
{body}
<aside class="cta"><p>{cta}</p></aside>
{footer}
</article>
</body>
</html>
"""
