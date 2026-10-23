"""Output file naming and the RenderedFile records returned to callers."""

from __future__ import annotations

from pathlib import Path

from memoria.models import RenderedFile


def check_basename(basename: str) -> None:
    if not basename or basename != Path(basename).name or basename in {".", ".."}:
        raise ValueError(f"basename must be a plain file name, got {basename!r}")


def describe(paths: list[Path], url_prefix: str) -> list[RenderedFile]:
    return [
        RenderedFile(
            format=path.suffix.lstrip("."), url=f"{url_prefix}/{path.name}", size_bytes=path.stat().st_size
        )
        for path in paths
    ]
