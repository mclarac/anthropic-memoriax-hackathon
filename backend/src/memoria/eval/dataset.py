"""Loads the on-disk eval datasets (see datasets/README.md)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from memoria.models import TenantProfile

ROUNDS = (1, 2, 3)


class Expectations(BaseModel):
    new_objection_keywords: list[str]
    competitive_update_keywords: list[str]
    conflict_keywords: list[str]
    canary: str


@dataclass(frozen=True)
class Round:
    number: int
    rep_utterances: list[str]
    fact_sheet: dict[str, str | None]
    expectations: Expectations
    documents: dict[str, str]  # filename -> markdown text


@dataclass(frozen=True)
class TenantDataset:
    slug: str
    profile: TenantProfile
    account_slug: str
    rep_slug: str
    rounds: dict[int, Round]

    @property
    def canary(self) -> str:
        return self.rounds[1].expectations.canary


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_round(directory: Path, number: int) -> Round:
    documents = {
        p.name: p.read_text(encoding="utf-8") for p in sorted((directory / "documents").glob("*.md"))
    }
    return Round(
        number=number,
        rep_utterances=_read_json(directory / "rep_utterances.json"),
        fact_sheet=_read_json(directory / "fact_sheet.json"),
        expectations=Expectations.model_validate(_read_json(directory / "expectations.json")),
        documents=documents,
    )


def load_tenant(directory: Path) -> TenantDataset:
    raw = _read_json(directory / "profile.json")
    account_slug, rep_slug = raw.pop("account_slug"), raw.pop("rep_slug")
    return TenantDataset(
        slug=directory.name,
        profile=TenantProfile.model_validate(raw),
        account_slug=account_slug,
        rep_slug=rep_slug,
        rounds={n: load_round(directory / f"round{n}", n) for n in ROUNDS},
    )


def load_datasets(root: Path) -> list[TenantDataset]:
    tenants = sorted(p for p in root.glob("tenant-*") if p.is_dir())
    if not tenants:
        raise FileNotFoundError(f"no tenant-* directories under {root}")
    return [load_tenant(p) for p in tenants]
