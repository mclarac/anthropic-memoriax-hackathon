import asyncio
import datetime

import pytest
from pydantic import ValidationError

from memoria.chain_prompts import CHAIN, INTERVIEWER_SYSTEM, SLOT_EXTRACTOR_SCHEMA, SLOT_EXTRACTOR_SYSTEM
from memoria.interview import PRIORITY_SLOTS, InterviewEngine
from memoria.models import (
    InterviewComplete,
    MemoriaDelta,
    MemoriaSentence,
    MemoriaTurnDone,
    Session,
    SlotsChanged,
    Tenant,
    TenantProfile,
    Turn,
)
from memoria.ports import LLMRequest, LLMResult

TODAY = datetime.date(2026, 10, 23)
CHAIN_BY_ID = {entry["id"]: entry for entry in CHAIN}


class ScriptedLLM:
    def __init__(self, deltas=("Hello there. ", "What is next?"), updates=(), extractor_gate=None):
        self.deltas = list(deltas)
        self.updates = list(updates)
        self.extractor_gate = extractor_gate
        self.stream_requests: list[LLMRequest] = []
        self.complete_requests: list[LLMRequest] = []
        self.stream_error: Exception | None = None
        self.extractor_error: Exception | None = None
        self.extractor_cancelled = False

    async def stream(self, req):
        self.stream_requests.append(req)
        if self.stream_error:
            raise self.stream_error
        for delta in self.deltas:
            await asyncio.sleep(0)
            yield delta

    async def complete(self, req):
        self.complete_requests.append(req)
        try:
            if self.extractor_gate is not None:
                await self.extractor_gate.wait()
            if self.extractor_error:
                raise self.extractor_error
        except asyncio.CancelledError:
            self.extractor_cancelled = True
            raise
        return LLMResult(text="", data={"updates": self.updates})


def update(slot, value="v", status="confirmed", quote="q", **extra):
    return {
        "slot": slot, "value": value, "status": status, "evidence_quote": quote,
        "conflicts_with": None, "needs_spelling_check": False, **extra,
    }


@pytest.fixture
def tenant():
    return Tenant(
        id="t1",
        profile=TenantProfile(
            name="Halden Analytics",
            offering_summary="Data-quality monitoring software.",
            brand_voice="Plain and direct.",
            approved_claims=["Monitors 10,000 tables"],
            forbidden_claims=["Guarantees zero incidents"],
        ),
    )


@pytest.fixture
def session():
    return Session(id="s1", tenant_id="t1", account_slug="brightwater", rep_slug="dana")


def engine(llm, **kwargs):
    return InterviewEngine(llm, lambda: TODAY, **kwargs)


async def collect(agen):
    return [event async for event in agen]


def test_priority_slots_are_in_the_specified_order():
    assert PRIORITY_SLOTS == [
        "next_meeting", "win_condition", "pain", "metrics", "decision_process", "economic_buyer",
        "objections", "competition", "champion", "paper_process", "assets_requested",
    ]


async def test_opening_streams_deltas_sentences_and_turn_done(session, tenant):
    llm = ScriptedLLM(deltas=["Hi, I'm Mem", "oria. Tell me ", "about the deal. ", "When is the call?"])
    events = await collect(engine(llm).opening(session, tenant))

    assert [e.text for e in events if isinstance(e, MemoriaDelta)] == [
        "Hi, I'm Mem", "oria. Tell me ", "about the deal. ", "When is the call?",
    ]
    sentences = [e for e in events if isinstance(e, MemoriaSentence)]
    assert [(s.index, s.text) for s in sentences] == [
        (0, "Hi, I'm Memoria."), (1, "Tell me about the deal."), (2, "When is the call?"),
    ]
    assert isinstance(events[-1], MemoriaTurnDone)
    assert events[-1].text == "Hi, I'm Memoria. Tell me about the deal. When is the call?"
    assert session.turns == [Turn(speaker="memoria", text=events[-1].text)]
    assert llm.complete_requests == []


async def test_opening_request_uses_chain_settings_and_prompt_assembly(session, tenant):
    llm = ScriptedLLM()
    await collect(engine(llm).opening(session, tenant))

    (req,) = llm.stream_requests
    settings = CHAIN_BY_ID["interviewer"]
    assert req.stage == "interviewer"
    assert req.system == INTERVIEWER_SYSTEM
    assert req.max_tokens == settings["max_tokens"]
    assert req.effort == settings["effort"]
    assert req.schema is None
    for fragment in (
        "Halden Analytics", "Data-quality monitoring software.", "Plain and direct.",
        "Monitors 10,000 tables", "Guarantees zero incidents", "=== TENANT PROFILE",
    ):
        assert fragment in req.tenant_block
    assert "(no memory for this account yet)" in req.user
    assert session.board.render() in req.user
    assert "Today is 2026-10-23." in req.user
    assert req.user.split("=== CONVERSATION SO FAR ===\n")[1].startswith("(")


async def test_memory_snapshot_includes_only_this_accounts_playbook_and_rep_files(session, tenant):
    session.memory_snapshot = {
        "/accounts/brightwater/objections.md": "O1 budget",
        "/accounts/brightwater/profile.md": "Utility, 40 sites",
        "/accounts/other-co/profile.md": "SECRET OTHER ACCOUNT",
        "/playbook/what-worked.md": "Lead with risk",
        "/reps/dana.md": "Likes short briefs",
        "/reps/sam.md": "SECRET OTHER REP",
        "/README.md": "policy v1",
    }
    llm = ScriptedLLM()
    await collect(engine(llm).opening(session, tenant))

    user = llm.stream_requests[0].user
    assert "--- /accounts/brightwater/objections.md ---\nO1 budget" in user
    assert "--- /accounts/brightwater/profile.md ---\nUtility, 40 sites" in user
    assert "--- /playbook/what-worked.md ---\nLead with risk" in user
    assert "--- /reps/dana.md ---\nLikes short briefs" in user
    assert "SECRET" not in user
    assert "policy v1" not in user
    assert "(no memory for this account yet)" not in user


async def test_account_slug_prefix_does_not_match_longer_slugs(session, tenant):
    session.memory_snapshot = {"/accounts/brightwater-east/profile.md": "SECRET"}
    llm = ScriptedLLM()
    await collect(engine(llm).opening(session, tenant))
    assert "SECRET" not in llm.stream_requests[0].user
    assert "(no memory for this account yet)" in llm.stream_requests[0].user


async def test_handle_utterance_interviewer_sees_conversation_including_new_rep_line(session, tenant):
    session.turns = [Turn(speaker="memoria", text="When is the call?")]
    llm = ScriptedLLM()
    await collect(engine(llm).handle_utterance(session, tenant, "Friday at ten"))

    conversation = llm.stream_requests[0].user.split("=== CONVERSATION SO FAR ===\n")[1]
    assert conversation.startswith("Memoria: When is the call?\nRep: Friday at ten")
    assert [t.speaker for t in session.turns] == ["memoria", "rep", "memoria"]
    assert session.turns[1].text == "Friday at ten"
    assert session.turns[2].text == "Hello there. What is next?"


async def test_handle_utterance_extractor_request_shape(session, tenant):
    session.turns = [Turn(speaker="memoria", text="When is the call?")]
    llm = ScriptedLLM()
    await collect(engine(llm).handle_utterance(session, tenant, "Friday at ten"))

    (req,) = llm.complete_requests
    settings = CHAIN_BY_ID["slot_extractor"]
    assert req.stage == "slot_extractor"
    assert req.system == SLOT_EXTRACTOR_SYSTEM
    assert req.schema == SLOT_EXTRACTOR_SCHEMA
    assert req.max_tokens == settings["max_tokens"]
    assert req.effort == settings["effort"]
    assert "next_meeting: [open] -" in req.user
    assert "=== MEMORIA'S LAST QUESTION ===\nWhen is the call?" in req.user
    assert req.user.endswith("=== REP UTTERANCE (speech-recognition output) ===\nFriday at ten")


async def test_slots_changed_updates_board_and_carries_validated_updates(session, tenant):
    llm = ScriptedLLM(updates=[update("next_meeting", "Friday 10:00", quote="Friday at ten")])
    events = await collect(engine(llm).handle_utterance(session, tenant, "Friday at ten"))

    (changed,) = [e for e in events if isinstance(e, SlotsChanged)]
    assert [(u.slot, u.value) for u in changed.updates] == [("next_meeting", "Friday 10:00")]
    assert changed.board.slots["next_meeting"].status == "confirmed"
    assert session.board.slots["next_meeting"].value == "Friday 10:00"
    assert session.board.slots["next_meeting"].evidence_quote == "Friday at ten"


async def test_updates_for_unknown_slots_are_dropped(session, tenant):
    llm = ScriptedLLM(updates=[update("favourite_colour", "blue"), update("pain", "late data")])
    events = await collect(engine(llm).handle_utterance(session, tenant, "x"))

    (changed,) = [e for e in events if isinstance(e, SlotsChanged)]
    assert [u.slot for u in changed.updates] == ["pain"]
    assert "favourite_colour" not in session.board.slots


async def test_malformed_extractor_output_raises(session, tenant):
    llm = ScriptedLLM(updates=[update("pain", status="open")])
    with pytest.raises(ValidationError):
        await collect(engine(llm).handle_utterance(session, tenant, "x"))


async def test_deltas_are_yielded_while_the_extractor_is_still_running(session, tenant):
    gate = asyncio.Event()
    llm = ScriptedLLM(extractor_gate=gate, updates=[update("pain", "late data")])
    stream = engine(llm).handle_utterance(session, tenant, "x")

    first = await asyncio.wait_for(anext(stream), timeout=1)
    assert isinstance(first, MemoriaDelta)
    assert session.board.slots["pain"].status == "open"

    gate.set()
    rest = await collect(stream)
    assert any(isinstance(e, SlotsChanged) for e in rest)
    assert session.board.slots["pain"].status == "confirmed"


async def test_turn_done_can_precede_slots_changed_when_the_extractor_is_slower(session, tenant):
    gate = asyncio.Event()
    llm = ScriptedLLM(extractor_gate=gate, updates=[update("pain", "late data")])
    kinds = []
    async for event in engine(llm).handle_utterance(session, tenant, "x"):
        kinds.append(type(event))
        if isinstance(event, MemoriaTurnDone):
            gate.set()
    assert kinds.index(MemoriaTurnDone) < kinds.index(SlotsChanged)


async def fill(session, statuses=("confirmed",)):
    for i, name in enumerate(PRIORITY_SLOTS):
        session.board.slots[name].status = statuses[i % len(statuses)]


async def test_interview_complete_when_every_priority_slot_is_confirmed_or_unsure(session, tenant):
    await fill(session, ("confirmed", "rep_unsure"))
    session.board.slots["pain"].status = "open"
    llm = ScriptedLLM(updates=[update("pain", None, "rep_unsure")])
    events = await collect(engine(llm).handle_utterance(session, tenant, "no idea"))

    assert events[-1] == InterviewComplete(reason="slots_filled")


async def test_non_priority_slots_do_not_block_completion(session, tenant):
    await fill(session)
    assert session.board.slots["decision_criteria"].status == "open"
    events = await collect(engine(ScriptedLLM()).handle_utterance(session, tenant, "ok"))
    assert events[-1] == InterviewComplete(reason="slots_filled")


async def test_conflict_status_keeps_interview_going(session, tenant):
    await fill(session)
    llm = ScriptedLLM(updates=[update("economic_buyer", "CIO", "conflict", conflicts_with="CFO")])
    events = await collect(engine(llm).handle_utterance(session, tenant, "now it's the CIO"))
    assert not any(isinstance(e, InterviewComplete) for e in events)


async def test_no_completion_event_while_slots_are_open(session, tenant):
    events = await collect(engine(ScriptedLLM()).handle_utterance(session, tenant, "hi"))
    assert not any(isinstance(e, InterviewComplete) for e in events)


async def test_turn_limit_reached_on_the_last_allowed_rep_turn(session, tenant):
    eng = engine(ScriptedLLM(), max_rep_turns=2)
    first = await collect(eng.handle_utterance(session, tenant, "one"))
    second = await collect(eng.handle_utterance(session, tenant, "two"))

    assert not any(isinstance(e, InterviewComplete) for e in first)
    assert second[-1] == InterviewComplete(reason="turn_limit")


async def test_slots_filled_wins_over_turn_limit(session, tenant):
    await fill(session)
    events = await collect(engine(ScriptedLLM(), max_rep_turns=1).handle_utterance(session, tenant, "x"))
    assert events[-1] == InterviewComplete(reason="slots_filled")


async def test_default_turn_limit_is_25(session, tenant):
    session.turns = [Turn(speaker="rep", text="r") for _ in range(24)]
    events = await collect(engine(ScriptedLLM()).handle_utterance(session, tenant, "the 25th"))
    assert events[-1] == InterviewComplete(reason="turn_limit")


async def test_interviewer_errors_propagate(session, tenant):
    llm = ScriptedLLM()
    llm.stream_error = RuntimeError("api down")
    with pytest.raises(RuntimeError, match="api down"):
        await collect(engine(llm).handle_utterance(session, tenant, "x"))


async def test_opening_errors_propagate(session, tenant):
    llm = ScriptedLLM()
    llm.stream_error = RuntimeError("api down")
    with pytest.raises(RuntimeError, match="api down"):
        await collect(engine(llm).opening(session, tenant))
    assert session.turns == []


async def test_extractor_errors_propagate(session, tenant):
    llm = ScriptedLLM()
    llm.extractor_error = RuntimeError("extractor down")
    with pytest.raises(RuntimeError, match="extractor down"):
        await collect(engine(llm).handle_utterance(session, tenant, "x"))


async def test_interviewer_failure_cancels_the_extractor(session, tenant):
    gate = asyncio.Event()
    llm = ScriptedLLM(extractor_gate=gate)
    llm.stream_error = RuntimeError("api down")
    with pytest.raises(RuntimeError):
        await collect(engine(llm).handle_utterance(session, tenant, "x"))
    assert llm.extractor_cancelled
