"""The simulated rep: plays a hidden fact sheet so the interview can be evaluated unattended."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from memoria.chain_prompts import SIMULATED_REP_SYSTEM, SIMULATED_REP_USER
from memoria.models import Turn
from memoria.ports import LLM, LLMRequest

_SPEAKER_LABEL = {"memoria": "Memoria", "rep": "Rep"}


class SimulatedRep:
    def __init__(self, llm: LLM, fact_sheet: Mapping[str, Any]) -> None:
        self._llm = llm
        self._fact_sheet = "\n".join(
            f"{slot}: {'unknown' if value is None else value}" for slot, value in fact_sheet.items()
        )

    async def next_utterance(self, turns: list[Turn]) -> str:
        conversation = "\n".join(f"{_SPEAKER_LABEL[t.speaker]}: {t.text}" for t in turns)
        user = SIMULATED_REP_USER.substitute(fact_sheet=self._fact_sheet, conversation=conversation)
        reply = await self._llm.complete(
            LLMRequest(
                stage="simulated_rep", system=SIMULATED_REP_SYSTEM, user=user, max_tokens=200, effort="low"
            )
        )
        return reply.text.strip()
