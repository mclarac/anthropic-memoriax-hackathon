"""Deterministic LLM for tests and MEMORIA_MODE=fake.

The interviewer and slot extractor react to the slot board in the prompt, so a
fake session fills the board the way a real one does. Every other stage returns
a fixed, schema-valid fixture describing one fictional deal.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import AsyncIterator
from functools import cache
from importlib import resources
from typing import Any

from memoria.chain_prompts import ASSET_TYPES
from memoria.interview import PRIORITY_SLOTS
from memoria.ports import LLMRequest, LLMResult

QUESTIONS = {
    "next_meeting": "When is your next meeting with this account, and who will be in the room?",
    "win_condition": "What does a win look like for that meeting?",
    "pain": "What is the main problem they are trying to solve?",
    "metrics": "Which numbers does the customer use to measure that problem?",
    "decision_process": "How does the customer make a buying decision?",
    "economic_buyer": "Who holds the budget and signs off on the purchase?",
    "objections": "What objections have come up so far, and who raised them?",
    "competition": "Who else are they considering, or what do they do today?",
    "champion": "Who is your champion inside the account?",
    "paper_process": "What do procurement, legal and security review involve?",
    "assets_requested": "Which assets do you want me to build, and for which audience?",
}
CLOSING = "That covers everything I need. I am starting the build now."

_FIXTURE_STAGES = {"deal_brief", "retrieval", "research", "personas", "strategy", "verifier", "reviser"}
_SLOT_LINE = re.compile(r"^(\w+): \[(\w+)\]", re.MULTILINE)
_DONE = ("confirmed", "rep_unsure")
_UTTERANCE_HEADER = "=== REP UTTERANCE (speech-recognition output) ===\n"
_REVISER_ASSET = re.compile(r"=== ASSET ===\n(.*?)\n\n=== VERIFIER REPORT ===", re.DOTALL)


@cache
def _fixture(name: str) -> dict[str, Any]:
    path = resources.files("memoria.fakes").joinpath("fixtures", f"{name}.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _open_priority_slot(prompt: str) -> str | None:
    """First priority slot not yet confirmed or marked unsure, read from the board in the prompt."""
    board = prompt.split("=== SLOT BOARD ===", 1)[-1].split("===", 1)[0]
    statuses = dict(_SLOT_LINE.findall(board))
    return next((slot for slot in PRIORITY_SLOTS if statuses.get(slot, "open") not in _DONE), None)


class FakeLLM:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def complete(self, req: LLMRequest) -> LLMResult:
        self.requests.append(req)
        if req.stage == "slot_extractor":
            return self._result(self._extract_slot(req.user))
        return self._result(self._fixture_for(req))

    async def stream(self, req: LLMRequest) -> AsyncIterator[str]:
        self.requests.append(req)
        if req.stage != "interviewer":
            raise ValueError(f"FakeLLM has no streaming script for stage {req.stage}")
        slot = _open_priority_slot(req.user)
        words = (QUESTIONS[slot] if slot else CLOSING).split(" ")
        for i, word in enumerate(words):
            yield word if i == len(words) - 1 else word + " "

    @staticmethod
    def _result(data: dict[str, Any]) -> LLMResult:
        return LLMResult(text=json.dumps(data), data=data, stop_reason="end_turn")

    @staticmethod
    def _extract_slot(prompt: str) -> dict[str, Any]:
        slot = _open_priority_slot(prompt)
        if slot is None:
            return {"updates": []}
        utterance = prompt.split(_UTTERANCE_HEADER, 1)[-1]
        return {"updates": [{
            "slot": slot,
            "value": utterance,
            "status": "confirmed",
            "evidence_quote": utterance,
            "conflicts_with": None,
            "needs_spelling_check": False,
        }]}

    @staticmethod
    def _fixture_for(req: LLMRequest) -> dict[str, Any]:
        stage, _, asset_type = req.stage.partition(":")
        if stage == "asset" and asset_type in ASSET_TYPES:
            return copy.deepcopy(_fixture(f"asset_{asset_type}"))
        if stage not in _FIXTURE_STAGES:
            raise ValueError(f"FakeLLM has no fixture for stage {req.stage}")
        if stage == "reviser" and (match := _REVISER_ASSET.search(req.user)):
            return json.loads(match.group(1))
        return copy.deepcopy(_fixture(stage))
