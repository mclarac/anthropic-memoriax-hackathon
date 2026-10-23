"""Shared test doubles for the orchestrator tests.

The doubles satisfy the protocols in memoria.ports and record what they were asked, so
tests can assert on requests whose shape is the behavior (stage names, schemas, documents).
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from memoria.models import RenderedFile, TenantProfile
from memoria.ports import AgentRunResult, LLMRequest, LLMResult

TODAY = date(2026, 10, 23)


def evidence(entry_id: str, claim: str = "a fact", **overrides: Any) -> dict[str, Any]:
    return {
        "id": entry_id, "kind": "uploaded_doc", "applies_to": "our_offering", "claim": claim,
        "quote": claim, "source": "doc.md", "source_date": None, "retrieved_on": "2026-10-23",
        "conflict_note": None, **overrides,
    }


def brief(assets_requested: list[str] | None = None, **campaign: Any) -> dict[str, Any]:
    return {
        "account_name": "Globex",
        "campaign": {
            "goal": "win", "assets_requested": ["deck"] if assets_requested is None else assets_requested,
            "audience_notes": None, "deadline": None, "brand_constraints": "plain words",
            "forbidden_claims": ["guaranteed ROI"], **campaign,
        },
    }


def plan_entry(asset_type: str) -> dict[str, Any]:
    return {"asset_type": asset_type, "persona_ids": ["P1"], "goal": f"{asset_type} goal",
            "key_messages": [], "length_hint": "short"}


def asset_content(asset_type: str, title: str = "Title") -> dict[str, Any]:
    content: dict[str, Any] = {"title": title, "placeholders": []}
    if asset_type == "email_sequence":
        content.pop("title")
    return content


def verdict(asset_verdict: str) -> dict[str, Any]:
    return {"claims": [], "rule_breaches": [], "asset_verdict": asset_verdict}


def full_script(**overrides: Any) -> dict[str, Any]:
    """Responses for every chain stage; tests override the stages they care about."""
    script: dict[str, Any] = {
        "deal_brief": brief(),
        "retrieval": {"entries": [evidence("E1")]},
        "research": {"questions": [], "entries": []},
        "personas": {"personas": []},
        "strategy": {"headline": "win", "asset_plan": [plan_entry("deck")]},
        "asset:*": lambda req: asset_content(req.stage.split(":", 1)[1]),
        "verifier": verdict("pass"),
        "reviser": lambda req: {"title": "Revised", "placeholders": []},
    }
    script.update(overrides)
    return script


class ScriptedLLM:
    """Returns scripted structured data per stage name.

    A script value is a dict (returned every time), a list (consumed in order, the last
    item repeats), or a callable taking the request (sync or async). A key of "asset:*"
    matches every "asset:<type>" stage.
    """

    def __init__(self, script: dict[str, Any]) -> None:
        self.script = script
        self.requests: list[LLMRequest] = []

    def calls(self, stage: str) -> list[LLMRequest]:
        return [r for r in self.requests if r.stage == stage]

    async def complete(self, req: LLMRequest) -> LLMResult:
        self.requests.append(req)
        key = req.stage if req.stage in self.script else req.stage.split(":", 1)[0] + ":*"
        value = self.script[key]
        if isinstance(value, list):
            seen = len(self.calls(req.stage)) - 1
            value = value[min(seen, len(value) - 1)]
        if callable(value):
            value = value(req)
            if inspect.isawaitable(value):
                value = await value
        if isinstance(value, Exception):
            raise value
        return LLMResult(text="", data=value)

    async def stream(self, req: LLMRequest) -> AsyncIterator[str]:
        yield ""


class DictMemory:
    """MemoryStore double backed by a dict; agents mutate `files` directly."""

    def __init__(self, files: dict[str, str] | None = None) -> None:
        self.files = files or {}
        self.ensured: list[tuple[str, str]] = []

    async def ensure_store(self, tenant_id: str, tenant_name: str) -> str:
        self.ensured.append((tenant_id, tenant_name))
        return f"store-{tenant_id}"

    async def snapshot(self, memory_store_id: str, path_prefix: str = "/") -> dict[str, str]:
        return {p: c for p, c in self.files.items() if p.startswith(path_prefix)}


class ScriptedAgents:
    def __init__(self, memory: DictMemory, writes: dict[str, str] | None = None,
                 answer: str = "Since our last session: nothing") -> None:
        self.memory = memory
        self.writes = writes or {}
        self.answer = answer
        self.runs: list[dict[str, Any]] = []

    async def run(self, **kwargs: Any) -> AgentRunResult:
        self.runs.append(kwargs)
        if kwargs["access"] == "read_write":
            self.memory.files.update(self.writes)
            return AgentRunResult(text="memory updated")
        return AgentRunResult(text=self.answer)


class SilentTTS:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def synthesize(self, text: str, voice: str | None = None) -> bytes:
        self.calls.append((text, voice))
        return b"RIFFwav"


class Doubles:
    """One wired set of doubles."""

    def __init__(self, script: dict[str, Any] | None = None, writes: dict[str, str] | None = None) -> None:
        self.llm = ScriptedLLM(script or full_script())
        self.memory = DictMemory()
        self.agents = ScriptedAgents(self.memory, writes if writes is not None else {"/a.md": "x"})
        self.tts = SilentTTS()


class RenderRecorder:
    """Stands in for memoria.renderers.render_asset: writes one markdown file per asset."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, asset_type: str, content: dict[str, Any], ledger: list[dict[str, Any]],
                 out_dir: Path, basename: str, url_prefix: str) -> list[RenderedFile]:
        self.calls.append({"asset_type": asset_type, "content": content, "ledger": ledger,
                           "out_dir": out_dir, "basename": basename, "url_prefix": url_prefix})
        path = out_dir / f"{basename}.md"
        path.write_text(str(content))
        return [RenderedFile(format="md", url=f"{url_prefix}/{path.name}", size_bytes=path.stat().st_size)]


@pytest.fixture
def doubles() -> Doubles:
    return Doubles()


@pytest.fixture
def render_recorder(monkeypatch) -> RenderRecorder:
    recorder = RenderRecorder()
    monkeypatch.setattr("memoria.chain.render_asset", recorder)
    return recorder


@pytest.fixture
def profile() -> TenantProfile:
    return TenantProfile(
        name="Acme", offering_summary="Payroll software", brand_voice="warm and plain",
        forbidden_claims=["cheapest on the market"], default_assets=["document"],
    )

