"""Renders a verified asset's structured content into its deliverable files."""

from __future__ import annotations

from pathlib import Path

from memoria.models import RenderedFile
from memoria.renderers.blog import render_blog
from memoria.renderers.deck import render_deck
from memoria.renderers.docx_render import render_docx
from memoria.renderers.emails import render_email_sequence
from memoria.renderers.files import check_basename, describe
from memoria.renderers.longform import build_longform
from memoria.renderers.pdf_render import render_pdf

_ASSET_TYPES = ("deck", "document", "blog", "email_sequence", "whitepaper")


def render_asset(
    asset_type: str,
    content: dict,
    ledger: list[dict],
    out_dir: Path,
    basename: str,
    url_prefix: str,
) -> list[RenderedFile]:
    """Write the files for one asset and return them with URLs under url_prefix."""
    if asset_type not in _ASSET_TYPES:
        raise ValueError(f"unknown asset_type {asset_type!r}; expected one of {', '.join(_ASSET_TYPES)}")
    check_basename(basename)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if asset_type == "deck":
        paths = render_deck(content, ledger, out_dir, basename)
    elif asset_type == "blog":
        paths = render_blog(content, ledger, out_dir, basename)
    elif asset_type == "email_sequence":
        paths = render_email_sequence(content, ledger, out_dir, basename)
    else:
        longform = build_longform(asset_type, content, ledger)
        paths = [out_dir / f"{basename}.docx", out_dir / f"{basename}.pdf"]
        render_docx(longform, paths[0])
        render_pdf(longform, paths[1])
    return describe(paths, url_prefix)
