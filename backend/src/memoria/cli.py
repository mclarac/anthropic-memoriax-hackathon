"""Command line: run the API server, or run one Card D round against a dataset tenant."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import uvicorn

from memoria.api import start_session
from memoria.app import Ports, build_ports
from memoria.chain import BuildRunner
from memoria.chain_prompts import TRACK_TEST_QUESTION
from memoria.config import Settings
from memoria.interview import InterviewEngine
from memoria.models import (
    InterviewComplete,
    Session,
    SessionCreate,
    StageEvent,
    Tenant,
    TenantProfile,
)
from memoria.storage import NotFoundError, Storage, document_media_type

logger = logging.getLogger(__name__)


class DatasetError(ValueError):
    """The dataset directory is missing a file the round needs, or a file is malformed."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise DatasetError(f"missing {path}") from None
    except json.JSONDecodeError as exc:
        raise DatasetError(f"{path} is not valid JSON: {exc}") from exc


def _load_profile(dataset: Path) -> tuple[TenantProfile, str, str]:
    data = _read_json(dataset / "profile.json")
    try:
        account_slug, rep_slug = data.pop("account_slug"), data.pop("rep_slug")
    except KeyError as exc:
        raise DatasetError(f"{dataset / 'profile.json'} needs {exc} (the account and rep slugs)") from None
    return TenantProfile.model_validate(data), account_slug, rep_slug


def _load_utterances(round_dir: Path) -> list[str]:
    utterances = _read_json(round_dir / "rep_utterances.json")
    if not isinstance(utterances, list) or not all(isinstance(u, str) for u in utterances):
        raise DatasetError(f"{round_dir / 'rep_utterances.json'} must be a list of strings")
    return utterances


def _ensure_tenant(storage: Storage, dataset: Path, profile: TenantProfile) -> Tenant:
    tenant_id = storage.dataset_tenant_id(dataset.name)
    if tenant_id is not None:
        try:
            return storage.get_tenant(tenant_id)
        except NotFoundError:
            logger.warning("tenant %s for dataset %s is gone from the data directory; creating a new one",
                           tenant_id, dataset.name)
    tenant = storage.create_tenant(profile)
    storage.remember_dataset_tenant(dataset.name, tenant.id)
    return tenant


def _upload_round_documents(storage: Storage, tenant_id: str, round_dir: Path, account_slug: str) -> None:
    for path in sorted((round_dir / "documents").glob("*")):
        media_type = document_media_type(path.name)
        if media_type is None:
            raise DatasetError(f"{path} is not a PDF, DOCX, MD or TXT document")
        storage.add_document(
            tenant_id, filename=path.name, media_type=media_type, data=path.read_bytes(),
            scope="account", account_slug=account_slug,
        )


async def _interview(engine: InterviewEngine, session: Session, tenant: Tenant, utterances: list[str],
                     storage: Storage) -> None:
    """Feed utterances one by one until the engine ends the interview or they run out."""
    async for _ in engine.opening(session, tenant):
        pass
    storage.save_session(session)
    for text in utterances:
        complete = False
        async for event in engine.handle_utterance(session, tenant, text):
            complete = complete or isinstance(event, InterviewComplete)
        storage.save_session(session)
        if complete:
            return


def _report(session: Session, storage: Storage) -> str:
    rendered = storage.rendered_dir(session.id)
    lines = [f"Card D question: {TRACK_TEST_QUESTION}", "", "Strategy answer:", session.strategy_answer or "",
             "", "Assets:"]
    for asset in session.assets:
        lines.append(f"- {asset.asset_type}: {asset.title} [{asset.verdict}]")
        lines.extend(f"    {rendered / Path(f.url).name}" for f in asset.files)
    lines += ["", "Memory diff:"]
    lines += [f"- {c.change} {c.path}" for c in session.memory_diff] or ["- (no changes)"]
    return "\n".join(lines) + "\n"


async def run_card_d(
    settings: Settings, ports: Ports, dataset: Path, round_number: int, out_dir: Path,
) -> Path:
    """Run one round of a dataset tenant end to end and write the Card D report; return its path."""
    round_dir = dataset / f"round{round_number}"
    profile, account_slug, rep_slug = _load_profile(dataset)
    utterances = _load_utterances(round_dir)

    storage = Storage(settings.data_dir)
    tenant = _ensure_tenant(storage, dataset, profile)
    _upload_round_documents(storage, tenant.id, round_dir, account_slug)
    session = await start_session(
        ports, storage, SessionCreate(tenant_id=tenant.id, account_slug=account_slug, rep_slug=rep_slug),
    )
    tenant = storage.get_tenant(tenant.id)

    await _interview(InterviewEngine(ports.llm, date.today), session, tenant, utterances, storage)
    async for event in BuildRunner(ports, storage, date.today).run(session, tenant):
        if isinstance(event, StageEvent) and event.stage.status != "running":
            print(f"{event.stage.stage_id}: {event.stage.status}", flush=True)

    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"session{round_number}.txt"
    report_path.write_text(_report(session, storage), encoding="utf-8")
    return report_path


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="memoria")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="run the API on 0.0.0.0:8000")
    card_d = commands.add_parser("card-d", help="run one dataset round and write the Card D report")
    card_d.add_argument("--dataset", type=Path, required=True, help="dataset tenant directory")
    card_d.add_argument("--round", type=int, required=True, dest="round_number")
    card_d.add_argument("--out", type=Path, default=Path("outputs"))
    args = parser.parse_args(argv)

    if args.command == "serve":
        uvicorn.run("memoria.app:create_app", factory=True, host="0.0.0.0", port=8000)
        return

    settings = Settings()
    try:
        report = asyncio.run(
            run_card_d(settings, build_ports(settings), args.dataset, args.round_number, args.out)
        )
    except DatasetError as exc:
        print(f"memoria: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(f"wrote {report}")
