import json
import re
from pathlib import Path

import jsonschema
import pytest

from memoria import chain_prompts as cp
from memoria.fakes.llm import FakeLLM
from memoria.interview import PRIORITY_SLOTS
from memoria.models import SlotBoard, SlotUpdate
from memoria.ports import LLMRequest

FIXTURES = Path(__file__).parent.parent / "src" / "memoria" / "fakes" / "fixtures"
CHAIN_BY_ID = {entry["id"]: entry for entry in cp.CHAIN}


def board_text(**statuses: str) -> str:
    board = SlotBoard()
    for name, status in statuses.items():
        board.slots[name].status = status
    return board.render()


def interviewer_request(board: str) -> LLMRequest:
    user = cp.INTERVIEWER_USER.substitute(
        memory_snapshot="(none)", slot_board=board, conversation="Memoria: hi", today="2026-10-23"
    )
    return LLMRequest(stage="interviewer", system="s", user=user, max_tokens=200)


def extractor_request(board: str, utterance: str) -> LLMRequest:
    user = cp.SLOT_EXTRACTOR_USER.substitute(slot_board=board, last_question="q", rep_utterance=utterance)
    return LLMRequest(
        stage="slot_extractor", system="s", user=user, max_tokens=800, schema=cp.SLOT_EXTRACTOR_SCHEMA
    )


async def spoken(fake: FakeLLM, req: LLMRequest) -> list[str]:
    return [delta async for delta in fake.stream(req)]


async def test_interviewer_asks_for_the_first_open_priority_slot():
    fake = FakeLLM()
    first = "".join(await spoken(fake, interviewer_request(board_text())))
    second = "".join(await spoken(fake, interviewer_request(board_text(next_meeting="confirmed"))))

    assert first != second
    assert "meeting" in first.lower()
    assert first.endswith("?")
    assert "win" in second.lower()


async def test_interviewer_streams_word_by_word_and_joins_back_to_the_question():
    deltas = await spoken(FakeLLM(), interviewer_request(board_text()))
    assert len(deltas) > 3
    assert all(delta.strip() and " " not in delta.strip() for delta in deltas)
    assert "".join(deltas) == "".join(deltas).strip()


async def test_interviewer_is_deterministic():
    fake = FakeLLM()
    req = interviewer_request(board_text(next_meeting="confirmed", win_condition="rep_unsure"))
    assert await spoken(fake, req) == await spoken(fake, req)


async def test_interviewer_skips_rep_unsure_and_asks_about_conflicts_again():
    fake = FakeLLM()
    unsure = "".join(await spoken(fake, interviewer_request(board_text(next_meeting="rep_unsure"))))
    conflict = "".join(await spoken(fake, interviewer_request(board_text(next_meeting="conflict"))))
    assert "win" in unsure.lower()
    assert "meeting" in conflict.lower()


async def test_interviewer_questions_follow_priority_order_and_are_all_distinct():
    fake = FakeLLM()
    asked = []
    statuses: dict[str, str] = {}
    for slot in PRIORITY_SLOTS:
        asked.append("".join(await spoken(fake, interviewer_request(board_text(**statuses)))))
        statuses[slot] = "confirmed"
    assert len(set(asked)) == len(PRIORITY_SLOTS)


async def test_interviewer_closes_when_every_priority_slot_is_done():
    fake = FakeLLM()
    done = {slot: "confirmed" for slot in PRIORITY_SLOTS}
    closing = "".join(await spoken(fake, interviewer_request(board_text(**done))))
    assert "build" in closing.lower()
    assert "?" not in closing


async def test_non_priority_slots_do_not_affect_the_interviewer():
    fake = FakeLLM()
    done = {slot: "confirmed" for slot in PRIORITY_SLOTS}
    closing = "".join(await spoken(fake, interviewer_request(board_text(**done))))
    with_extra_open = "".join(await spoken(fake, interviewer_request(board_text(**done, audience="open"))))
    assert closing == with_extra_open


async def test_stream_records_the_request():
    fake = FakeLLM()
    req = interviewer_request(board_text())
    await spoken(fake, req)
    assert fake.requests == [req]


async def test_slot_extractor_confirms_the_first_open_priority_slot_with_the_utterance():
    fake = FakeLLM()
    req = extractor_request(board_text(next_meeting="confirmed"), "They want a final pitch Friday.")
    result = await fake.complete(req)

    assert result.data is not None
    (update,) = result.data["updates"]
    assert update["slot"] == "win_condition"
    assert update["status"] == "confirmed"
    assert update["value"] == "They want a final pitch Friday."
    assert update["evidence_quote"] == "They want a final pitch Friday."
    SlotUpdate.model_validate(update)
    jsonschema.validate(result.data, cp.SLOT_EXTRACTOR_SCHEMA)
    assert fake.requests == [req]


async def test_slot_extractor_keeps_multiline_utterance_intact():
    fake = FakeLLM()
    result = await fake.complete(extractor_request(board_text(), "line one\nline two"))
    assert result.data["updates"][0]["value"] == "line one\nline two"


async def test_slot_extractor_returns_no_updates_when_nothing_is_open():
    fake = FakeLLM()
    done = {slot: "confirmed" for slot in PRIORITY_SLOTS}
    result = await fake.complete(extractor_request(board_text(**done), "anything"))
    assert result.data == {"updates": []}


FIXTURE_SCHEMAS = {
    "deal_brief": cp.DEAL_BRIEF_SCHEMA,
    "retrieval": cp.LEDGER_SCHEMA,
    "research": cp.RESEARCH_FINAL_SCHEMA,
    "personas": cp.PERSONAS_SCHEMA,
    "strategy": cp.STRATEGY_SCHEMA,
    "verifier": cp.VERIFIER_SCHEMA,
    "reviser": cp.ASSET_SCHEMAS["document"],
    **{f"asset_{t}": cp.ASSET_SCHEMAS[t] for t in cp.ASSET_TYPES},
}


@pytest.mark.parametrize("name", sorted(FIXTURE_SCHEMAS))
def test_fixture_validates_against_its_chain_schema(name):
    data = json.loads((FIXTURES / f"{name}.json").read_text())
    jsonschema.validate(data, FIXTURE_SCHEMAS[name])


@pytest.mark.parametrize("stage", ["deal_brief", "retrieval", "research", "personas", "strategy", "verifier"])
async def test_backfill_stages_return_their_fixture(stage):
    fake = FakeLLM()
    schema = CHAIN_BY_ID[stage]["schema"]
    result = await fake.complete(LLMRequest(stage=stage, system="s", user="u", max_tokens=10, schema=schema))

    assert result.data == json.loads((FIXTURES / f"{stage}.json").read_text())
    assert json.loads(result.text) == result.data
    jsonschema.validate(result.data, schema)


@pytest.mark.parametrize("asset_type", cp.ASSET_TYPES)
async def test_asset_stage_returns_the_matching_asset_fixture(asset_type):
    fake = FakeLLM()
    schema = cp.ASSET_SCHEMAS[asset_type]
    result = await fake.complete(
        LLMRequest(stage=f"asset:{asset_type}", system="s", user="u", max_tokens=10, schema=schema)
    )
    jsonschema.validate(result.data, schema)
    assert result.data == json.loads((FIXTURES / f"asset_{asset_type}.json").read_text())


async def test_reviser_returns_the_asset_from_the_prompt_when_it_parses():
    fake = FakeLLM()
    asset = json.loads((FIXTURES / "asset_blog.json").read_text())
    user = cp.REVISER_USER.substitute(asset_json=json.dumps(asset, indent=2), verifier_report="{}")
    result = await fake.complete(LLMRequest(stage="reviser", system="s", user=user, max_tokens=10))
    assert result.data == asset


async def test_reviser_falls_back_to_its_fixture_when_the_prompt_has_no_asset_section():
    fake = FakeLLM()
    result = await fake.complete(LLMRequest(stage="reviser", system="s", user="fix it", max_tokens=10))
    assert result.data == json.loads((FIXTURES / "reviser.json").read_text())


async def test_fixture_results_are_independent_copies():
    fake = FakeLLM()
    req = LLMRequest(stage="strategy", system="s", user="u", max_tokens=10)
    first = await fake.complete(req)
    first.data["headline"] = "mutated"
    second = await fake.complete(req)
    assert second.data["headline"] != "mutated"


async def test_unknown_stage_is_an_error():
    with pytest.raises(ValueError, match="no_such_stage"):
        await FakeLLM().complete(LLMRequest(stage="no_such_stage", system="s", user="u", max_tokens=1))


async def test_unknown_asset_type_is_an_error():
    with pytest.raises(ValueError, match="asset:podcast"):
        await FakeLLM().complete(LLMRequest(stage="asset:podcast", system="s", user="u", max_tokens=1))


async def test_streaming_a_stage_without_a_script_is_an_error():
    with pytest.raises(ValueError, match="deal_brief"):
        await spoken(FakeLLM(), LLMRequest(stage="deal_brief", system="s", user="u", max_tokens=1))


# Coherence of the fictional deal across fixtures.

def load(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def ledger_ids() -> set[str]:
    return {e["id"] for e in load("retrieval")["entries"]} | {e["id"] for e in load("research")["entries"]}


def cited_ids(node) -> set[str]:
    return set(re.findall(r"\[(E\d+)\]", json.dumps(node))) | _id_lists(node)


def _id_lists(node) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("evidence_ids", "proof_evidence_ids"):
                found |= set(value)
            else:
                found |= _id_lists(value)
    elif isinstance(node, list):
        for item in node:
            found |= _id_lists(item)
    return found


def test_ledger_ids_are_unique():
    ids = [e["id"] for e in load("retrieval")["entries"]] + [e["id"] for e in load("research")["entries"]]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("name", ["personas", "strategy", *[f"asset_{t}" for t in cp.ASSET_TYPES]])
def test_every_cited_evidence_id_exists_in_the_ledger(name):
    cited = cited_ids(load(name))
    assert cited
    assert cited <= ledger_ids()


def test_verifier_fixture_passes():
    assert load("verifier")["asset_verdict"] == "pass"


def test_fixtures_describe_the_halden_brightwater_deal_and_never_ledgerline():
    everything = "".join(p.read_text() for p in FIXTURES.glob("*.json"))
    assert "Halden Analytics" in everything
    assert "Brightwater Utilities" in everything
    assert "ledgerline" not in everything.lower()


@pytest.mark.parametrize("asset_type", ["blog", "whitepaper"])
def test_public_assets_do_not_name_the_customer(asset_type):
    assert "Brightwater" not in json.dumps(load(f"asset_{asset_type}"))


def test_asset_fixtures_respect_prompt_limits():
    blog = load("asset_blog")
    assert len(blog["title"]) <= 60
    assert len(blog["meta_description"]) <= 155
    for email in load("asset_email_sequence")["emails"]:
        assert len(email["subject"].split()) <= 7
        assert len(email["body_text"].split()) <= 120


@pytest.mark.parametrize("asset_type", cp.ASSET_TYPES)
def test_listed_placeholders_appear_in_the_asset_text(asset_type):
    asset = load(f"asset_{asset_type}")
    text = json.dumps({k: v for k, v in asset.items() if k != "placeholders"})
    for placeholder in asset["placeholders"]:
        assert placeholder in text


async def test_fake_llm_drives_the_interview_engine_to_slots_filled():
    import datetime

    from memoria.interview import InterviewEngine
    from memoria.models import InterviewComplete, Session, Tenant, TenantProfile

    tenant = Tenant(id="t", profile=TenantProfile(name="Halden Analytics", offering_summary="Monitoring."))
    session = Session(id="s", tenant_id="t", account_slug="brightwater", rep_slug="dana")
    engine = InterviewEngine(FakeLLM(), lambda: datetime.date(2026, 10, 23))

    completed = None
    for n in range(1, len(PRIORITY_SLOTS) + 1):
        events = [e async for e in engine.handle_utterance(session, tenant, f"answer {n}")]
        completed = next((e for e in events if isinstance(e, InterviewComplete)), None)
        if completed:
            break

    assert completed == InterviewComplete(reason="slots_filled")
    assert n == len(PRIORITY_SLOTS)
    assert session.board.slots["next_meeting"].value == "answer 1"
