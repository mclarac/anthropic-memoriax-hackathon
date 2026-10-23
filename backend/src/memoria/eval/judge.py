"""LLM judge: one criterion per call, verdict on the first line."""

from __future__ import annotations

import re

from memoria.chain_prompts import JUDGE_CRITERIA, JUDGE_SYSTEM, JUDGE_USER
from memoria.eval.checks import CheckResult
from memoria.ports import LLM, LLMRequest

# "PASS" or "FAIL" alone, or followed by punctuation or a separator and a reason.
# Stricter than a prefix match so "PASS or FAIL" and "PASSED" are rejected.
_VERDICT = re.compile(r"^\W*(PASS|FAIL)\W*(?:[:\-–—]\s*\S.*)?$", re.IGNORECASE)


class Judge:
    def __init__(self, llm: LLM) -> None:
        self._llm = llm

    async def grade(self, criterion: str, output: str, context: str = "") -> CheckResult:
        """Grade `output` against JUDGE_CRITERIA[criterion].

        A reply whose first line is not a clear PASS or FAIL comes back as an errored,
        not-passed result. An LLM call failure raises, so the runner records an errored run.
        """
        user = JUDGE_USER.substitute(criterion=JUDGE_CRITERIA[criterion], context=context, output=output)
        reply = await self._llm.complete(
            LLMRequest(stage="judge", system=JUDGE_SYSTEM, user=user, max_tokens=200, effort="low")
        )
        first_line = reply.text.split("\n", 1)[0].strip()
        match = _VERDICT.match(first_line)
        if match is None:
            return CheckResult(
                criterion, False, f"unparseable judge reply: {reply.text[:80]!r}", errored=True
            )
        verdict = match.group(1).upper()
        reason = reply.text.split("\n", 1)[1].strip() if "\n" in reply.text else first_line
        return CheckResult(criterion, verdict == "PASS", reason)
