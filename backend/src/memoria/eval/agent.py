"""Wiring between the eval runner and the orchestrator."""

from __future__ import annotations

import json
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from memoria.api import start_session
from memoria.app import Ports, build_ports
from memoria.chain import BuildRunner
from memoria.config import Settings
from memoria.eval.dataset import Round, TenantDataset
from memoria.eval.runner import AgentFn, Task
from memoria.eval.simulated_rep import SimulatedRep
from memoria.interview import InterviewEngine
from memoria.models import InterviewComplete, Session, SessionCreate, Tenant, Turn
from memoria.storage import Storage, document_media_type

# Rendered formats that are plain text; docx, pptx and pdf are binary and would only add noise.
_TEXT_SUFFIXES = {".md", ".html", ".eml"}


def _upload_documents(storage: Storage, tenant_id: str, account_slug: str, rnd: Round) -> None:
    for filename, text in rnd.documents.items():
        storage.add_document(
            tenant_id, filename=filename, media_type=document_media_type(filename) or "text/markdown",
            data=text.encode("utf-8"), scope="account", account_slug=account_slug,
        )


class _ScriptedRep:
    """Replays the dataset's recorded utterances; fake mode has no LLM to play the fact sheet."""

    def __init__(self, utterances: list[str]) -> None:
        self._remaining = list(reversed(utterances))

    async def next_utterance(self, turns: list[Turn]) -> str | None:
        return self._remaining.pop() if self._remaining else None


async def _interview(engine: InterviewEngine, rep: SimulatedRep | _ScriptedRep, session: Session,
                     tenant: Tenant) -> None:
    async for _ in engine.opening(session, tenant):
        pass
    while (text := await rep.next_utterance(session.turns)) is not None:
        complete = False
        async for event in engine.handle_utterance(session, tenant, text):
            complete = complete or isinstance(event, InterviewComplete)
        if complete:
            return


def _texts(session: Session, storage: Storage) -> list[str]:
    texts = [t.text for t in session.turns if t.speaker == "memoria"]
    texts.append(session.strategy_answer or "")
    texts.append(json.dumps(session.artifacts.get("strategy"), default=str))
    rendered = storage.rendered_dir(session.id)
    for asset in session.assets:
        for file in asset.files:
            path = rendered / Path(file.url).name
            if path.suffix in _TEXT_SUFFIXES:
                texts.append(path.read_text(encoding="utf-8"))
    return texts


async def _run_rounds(
    ports: Ports, storage: Storage, dataset: TenantDataset, others: list[TenantDataset], through: int,
    scripted: bool,
) -> dict[str, Any]:
    # Other tenants share the data directory so the isolation check can fail if anything leaks.
    for other in others:
        foreign = storage.create_tenant(other.profile)
        _upload_documents(storage, foreign.id, other.account_slug, other.rounds[1])
    tenant = storage.create_tenant(dataset.profile)
    engine = InterviewEngine(ports.llm, date.today)
    runner = BuildRunner(ports, storage, date.today)
    previous_strategy: Any = None
    for number in range(1, through + 1):
        rnd = dataset.rounds[number]
        _upload_documents(storage, tenant.id, dataset.account_slug, rnd)
        session = await start_session(
            ports, storage,
            SessionCreate(tenant_id=tenant.id, account_slug=dataset.account_slug, rep_slug=dataset.rep_slug),
        )
        tenant = storage.get_tenant(tenant.id)
        rep = _ScriptedRep(rnd.rep_utterances) if scripted else SimulatedRep(ports.llm, rnd.fact_sheet)
        await _interview(engine, rep, session, tenant)
        async for _ in runner.run(session, tenant):
            pass
        if number < through:
            previous_strategy = session.artifacts["strategy"]
    assert tenant.memory_store_id is not None
    return {
        "board": session.board,
        "answer": session.strategy_answer or "",
        "strategy_before": previous_strategy,
        "strategy_after": session.artifacts["strategy"],
        "memory_snapshot": await ports.memory.snapshot(tenant.memory_store_id, "/"),
        "assets": session.assets,
        "texts": _texts(session, storage),
    }


def build_agent_fn(settings: Settings, datasets: list[TenantDataset]) -> AgentFn:
    """Each trial replays rounds 1..N for the task's tenant on fresh storage and memory."""
    by_slug = {d.slug: d for d in datasets}

    async def agent_fn(task: Task) -> dict[str, Any]:
        dataset = by_slug[task.tenant]
        others = [d for d in datasets if d.slug != task.tenant]
        with tempfile.TemporaryDirectory(prefix="memoria-eval-") as data_dir:
            trial_settings = settings.model_copy(update={"data_dir": Path(data_dir)})
            return await _run_rounds(
                build_ports(trial_settings), Storage(trial_settings.data_dir), dataset, others, task.round,
                scripted=settings.mode == "fake",
            )

    return agent_fn
