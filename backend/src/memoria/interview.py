"""The voice interview: Memoria's spoken turns and the slot board behind them."""

from __future__ import annotations

import asyncio
import datetime
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from memoria.chain_prompts import (
    CHAIN,
    INTERVIEWER_SYSTEM,
    INTERVIEWER_USER,
    SLOT_EXTRACTOR_SCHEMA,
    SLOT_EXTRACTOR_SYSTEM,
    SLOT_EXTRACTOR_USER,
    TENANT_BLOCK,
)
from memoria.models import (
    InterviewComplete,
    MemoriaDelta,
    MemoriaSentence,
    MemoriaTurnDone,
    Session,
    SlotsChanged,
    SlotUpdate,
    Tenant,
    Turn,
)
from memoria.ports import LLM, LLMRequest
from memoria.text import SentenceSplitter

PRIORITY_SLOTS = [
    "next_meeting", "win_condition", "pain", "metrics", "decision_process", "economic_buyer",
    "objections", "competition", "champion", "paper_process", "assets_requested",
]

_STAGE_SETTINGS = {entry["id"]: entry for entry in CHAIN}
_NO_MEMORY = "(no memory for this account yet)"
_NO_CONVERSATION = "(the conversation has not started)"

InterviewEvent = MemoriaDelta | MemoriaSentence | MemoriaTurnDone | SlotsChanged | InterviewComplete


class _ExtractorOutput(BaseModel):
    updates: list[SlotUpdate]


@dataclass
class _Failed:
    error: BaseException


@dataclass
class _ExtractorResult:
    updates: list[SlotUpdate]


@dataclass
class _TaskEnded:
    pass


class InterviewEngine:
    def __init__(
        self, llm: LLM, today: Callable[[], datetime.date], max_rep_turns: int = 25
    ) -> None:
        self._llm = llm
        self._today = today
        self._max_rep_turns = max_rep_turns

    async def opening(self, session: Session, tenant: Tenant) -> AsyncIterator[InterviewEvent]:
        async for event in self._speak(session, tenant):
            if isinstance(event, MemoriaTurnDone):
                session.turns.append(Turn(speaker="memoria", text=event.text))
            yield event

    async def handle_utterance(
        self, session: Session, tenant: Tenant, text: str
    ) -> AsyncIterator[InterviewEvent]:
        last_question = next((t.text for t in reversed(session.turns) if t.speaker == "memoria"), None)
        session.turns.append(Turn(speaker="rep", text=text))

        queue: asyncio.Queue[Any] = asyncio.Queue()
        tasks = [
            asyncio.create_task(self._guard(queue, self._pump_interviewer, queue, session, tenant)),
            asyncio.create_task(
                self._guard(queue, self._pump_extractor, queue, session, text, last_question)
            ),
        ]
        try:
            pending = len(tasks)
            while pending:
                item = await queue.get()
                if isinstance(item, _Failed):
                    raise item.error
                if isinstance(item, _TaskEnded):
                    pending -= 1
                elif isinstance(item, _ExtractorResult):
                    session.board.apply(item.updates)
                    yield SlotsChanged(updates=item.updates, board=session.board)
                else:
                    if isinstance(item, MemoriaTurnDone):
                        session.turns.append(Turn(speaker="memoria", text=item.text))
                    yield item
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        if self._slots_filled(session):
            yield InterviewComplete(reason="slots_filled")
        elif self._rep_turns(session) >= self._max_rep_turns:
            yield InterviewComplete(reason="turn_limit")

    @staticmethod
    async def _guard(
        queue: asyncio.Queue[Any], work: Callable[..., Awaitable[None]], *args: Any
    ) -> None:
        """Run one producer; report its failure through the queue so the consumer can raise it."""
        try:
            await work(*args)
        except Exception as exc:
            await queue.put(_Failed(exc))
        finally:
            await queue.put(_TaskEnded())

    async def _pump_interviewer(self, queue: asyncio.Queue[Any], session: Session, tenant: Tenant) -> None:
        async for event in self._speak(session, tenant):
            await queue.put(event)

    async def _pump_extractor(
        self, queue: asyncio.Queue[Any], session: Session, text: str, last_question: str | None
    ) -> None:
        settings = _STAGE_SETTINGS["slot_extractor"]
        result = await self._llm.complete(LLMRequest(
            stage="slot_extractor",
            system=SLOT_EXTRACTOR_SYSTEM,
            user=SLOT_EXTRACTOR_USER.substitute(
                slot_board=session.board.render(),
                last_question=last_question or "(none yet)",
                rep_utterance=text,
            ),
            max_tokens=settings["max_tokens"],
            effort=settings["effort"],
            schema=SLOT_EXTRACTOR_SCHEMA,
        ))
        output = _ExtractorOutput.model_validate(result.data)
        known = [u for u in output.updates if u.slot in session.board.slots]
        await queue.put(_ExtractorResult(known))

    async def _speak(self, session: Session, tenant: Tenant) -> AsyncIterator[InterviewEvent]:
        """Stream one interviewer turn as deltas, sentences, then the finished turn."""
        settings = _STAGE_SETTINGS["interviewer"]
        req = LLMRequest(
            stage="interviewer",
            system=INTERVIEWER_SYSTEM,
            tenant_block=TENANT_BLOCK.substitute(tenant_profile=_render_profile(tenant)),
            user=INTERVIEWER_USER.substitute(
                memory_snapshot=_render_memory(session),
                slot_board=session.board.render(),
                conversation=_render_conversation(session.turns),
                today=self._today().isoformat(),
            ),
            max_tokens=settings["max_tokens"],
            effort=settings["effort"],
        )
        splitter = SentenceSplitter()
        spoken: list[str] = []
        sentence_index = 0
        async for delta in self._llm.stream(req):
            spoken.append(delta)
            yield MemoriaDelta(text=delta)
            for sentence in splitter.feed(delta):
                yield MemoriaSentence(index=sentence_index, text=sentence)
                sentence_index += 1
        if (tail := splitter.flush()) is not None:
            yield MemoriaSentence(index=sentence_index, text=tail)
        yield MemoriaTurnDone(text="".join(spoken).strip())

    @staticmethod
    def _slots_filled(session: Session) -> bool:
        return all(session.board.slots[name].status in ("confirmed", "rep_unsure") for name in PRIORITY_SLOTS)

    @staticmethod
    def _rep_turns(session: Session) -> int:
        return sum(1 for t in session.turns if t.speaker == "rep")


def _render_profile(tenant: Tenant) -> str:
    profile = tenant.profile

    def listing(items: list[str]) -> str:
        return "\n".join(f"- {item}" for item in items) if items else "- (none)"

    return "\n".join([
        f"Name: {profile.name}",
        f"Offering: {profile.offering_summary}",
        f"Brand voice: {profile.brand_voice or '(not specified)'}",
        "Approved claims:",
        listing(profile.approved_claims),
        "Forbidden claims:",
        listing(profile.forbidden_claims),
    ])


def _render_memory(session: Session) -> str:
    account_prefix = f"/accounts/{session.account_slug}/"
    rep_path = f"/reps/{session.rep_slug}.md"
    files = [
        f"--- {path} ---\n{content}"
        for path, content in sorted(session.memory_snapshot.items())
        if path.startswith((account_prefix, "/playbook/")) or path == rep_path
    ]
    return "\n\n".join(files) if files else _NO_MEMORY


def _render_conversation(turns: list[Turn]) -> str:
    if not turns:
        return _NO_CONVERSATION
    return "\n".join(f"{'Memoria' if t.speaker == 'memoria' else 'Rep'}: {t.text}" for t in turns)
