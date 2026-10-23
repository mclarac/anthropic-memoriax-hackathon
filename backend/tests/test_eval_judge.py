import pytest

from memoria.chain_prompts import JUDGE_CRITERIA, JUDGE_SYSTEM
from memoria.eval.judge import Judge
from memoria.eval.simulated_rep import SimulatedRep
from memoria.models import Turn
from memoria.ports import LLMRequest, LLMResult


class ScriptedLLM:
    def __init__(self, *replies: str):
        self.replies = list(replies)
        self.requests: list[LLMRequest] = []

    async def complete(self, req: LLMRequest) -> LLMResult:
        self.requests.append(req)
        return LLMResult(text=self.replies.pop(0))

    def stream(self, req):
        raise NotImplementedError


class BrokenLLM:
    async def complete(self, req):
        raise TimeoutError("upstream timeout")


CRITERION = "leads_with_change"


@pytest.mark.parametrize(
    ("reply", "passed"),
    [
        ("PASS\nIt opens with the change.", True),
        ("FAIL\nNo mention of change.", False),
        ("pass\nlowercase is fine", True),
        ("PASS: inline reason", True),
        ("  FAIL.  \nreason", False),
        ("**PASS**\nreason", True),
    ],
)
async def test_parses_first_line_verdict(reply, passed):
    result = await Judge(ScriptedLLM(reply)).grade(CRITERION, output="x")
    assert result.passed is passed and not result.errored and result.name == CRITERION


@pytest.mark.parametrize(
    "reply",
    [
        "",
        "Looks good to me",
        "The answer would PASS",
        "PASS or FAIL",
        "PASSED\nreason",
        "\n\nPASS",
        "MAYBE\nPASS",
    ],
)
async def test_malformed_output_is_an_error_not_a_pass(reply):
    result = await Judge(ScriptedLLM(reply)).grade(CRITERION, output="x")
    assert not result.passed and result.errored
    assert "unparseable" in result.detail


async def test_llm_failure_propagates_so_the_runner_records_an_errored_run():
    with pytest.raises(TimeoutError):
        await Judge(BrokenLLM()).grade(CRITERION, output="x")


async def test_request_uses_judge_prompts_and_criterion_text():
    llm = ScriptedLLM("PASS\nok")
    await Judge(llm).grade(CRITERION, output="THE ANSWER", context="THE CONTEXT")
    req = llm.requests[0]
    assert req.system == JUDGE_SYSTEM
    assert JUDGE_CRITERIA[CRITERION] in req.user
    assert "THE ANSWER" in req.user and "THE CONTEXT" in req.user
    assert req.schema is None


async def test_unknown_criterion_is_rejected():
    with pytest.raises(KeyError):
        await Judge(ScriptedLLM("PASS")).grade("not_a_criterion", output="x")


async def test_simulated_rep_sends_fact_sheet_with_unknowns_marked():
    llm = ScriptedLLM("  uh the pain is basically slow deploys  ")
    rep = SimulatedRep(llm, {"pain": "slow deploys", "champion": None})
    text = await rep.next_utterance([Turn(speaker="memoria", text="What hurts most?")])
    assert text == "uh the pain is basically slow deploys"
    req = llm.requests[0]
    assert "slow deploys" in req.user and "champion: unknown" in req.user
    assert "Memoria: What hurts most?" in req.user
    assert req.stage == "simulated_rep"


async def test_simulated_rep_renders_both_speakers_in_order():
    llm = ScriptedLLM("ok")
    rep = SimulatedRep(llm, {"pain": "x"})
    await rep.next_utterance(
        [
            Turn(speaker="memoria", text="Q1"),
            Turn(speaker="rep", text="A1"),
            Turn(speaker="memoria", text="Q2"),
        ]
    )
    assert (
        llm.requests[0].user.index("Q1") < llm.requests[0].user.index("A1") < llm.requests[0].user.index("Q2")
    )
