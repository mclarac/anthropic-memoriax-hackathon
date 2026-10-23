"""Shared data contract between the API, the chain, memory, renderers and the web client.

Changing a model here changes the wire format. Update docs/contract.md and
web/src/lib/contract.ts in the same change.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from memoria.chain_prompts import ASSET_TYPES, SLOT_NAMES

AssetType = Literal["deck", "document", "blog", "email_sequence", "whitepaper"]
SlotStatus = Literal["confirmed", "rep_unsure", "open", "conflict"]
StageId = Literal[
    "deal_brief", "retrieval", "research", "personas", "strategy",
    "assets", "verifier", "memory_writer", "strategy_answer",
]
StageStatus = Literal["pending", "running", "done", "failed", "skipped"]
SessionPhase = Literal["interview", "building", "complete", "failed"]

assert set(AssetType.__args__) == set(ASSET_TYPES)  # keep in step with the prompts


# ── Tenants ─────────────────────────────────────────────────────────────────

class TenantProfile(BaseModel):
    """Everything Memoria knows about the seller before any documents."""
    name: str = Field(min_length=1)
    offering_summary: str = Field(min_length=1, description="What the tenant sells, in a paragraph.")
    brand_voice: str = ""
    approved_claims: list[str] = []
    forbidden_claims: list[str] = []
    default_assets: list[AssetType] = ["deck", "email_sequence"]


class Tenant(BaseModel):
    id: str
    profile: TenantProfile
    memory_store_id: str | None = None
    documents: list[DocumentRef] = []


class DocumentRef(BaseModel):
    id: str
    filename: str
    media_type: str
    size_bytes: int
    scope: Literal["tenant", "account"] = "tenant"
    account_slug: str | None = None


# ── Interview ───────────────────────────────────────────────────────────────

class Slot(BaseModel):
    value: str | None = None
    status: SlotStatus = "open"
    evidence_quote: str | None = None
    conflicts_with: str | None = None
    needs_spelling_check: bool = False


class SlotBoard(BaseModel):
    slots: dict[str, Slot] = Field(default_factory=lambda: {name: Slot() for name in SLOT_NAMES})

    def apply(self, updates: list[SlotUpdate]) -> None:
        for u in updates:
            self.slots[u.slot] = Slot(
                value=u.value, status=u.status, evidence_quote=u.evidence_quote,
                conflicts_with=u.conflicts_with, needs_spelling_check=u.needs_spelling_check,
            )

    def render(self) -> str:
        """Plain-text board for prompts: one slot per line."""
        lines = []
        for name, s in self.slots.items():
            value = s.value if s.value is not None else "-"
            lines.append(f"{name}: [{s.status}] {value}")
        return "\n".join(lines)


class SlotUpdate(BaseModel):
    slot: str
    value: str | None
    status: Literal["confirmed", "rep_unsure", "conflict"]
    evidence_quote: str
    conflicts_with: str | None = None
    needs_spelling_check: bool = False


class Turn(BaseModel):
    speaker: Literal["memoria", "rep"]
    text: str


# ── Build outputs ───────────────────────────────────────────────────────────

class StageState(BaseModel):
    stage_id: StageId
    status: StageStatus = "pending"
    detail: str | None = None
    duration_ms: int | None = None


class RenderedFile(BaseModel):
    format: Literal["pptx", "docx", "pdf", "md", "html", "eml"]
    url: str
    size_bytes: int


class AssetRef(BaseModel):
    asset_type: AssetType
    title: str
    verdict: Literal["pass", "needs_human_review"]
    placeholders: list[str] = []
    files: list[RenderedFile] = []


class MemoryChange(BaseModel):
    path: str
    change: Literal["added", "modified", "removed"]
    before: str | None = None
    after: str | None = None


# ── Session ─────────────────────────────────────────────────────────────────

class SessionCreate(BaseModel):
    tenant_id: str
    account_slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    rep_slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")


class Session(BaseModel):
    id: str
    tenant_id: str
    account_slug: str
    rep_slug: str
    phase: SessionPhase = "interview"
    turns: list[Turn] = []
    board: SlotBoard = Field(default_factory=SlotBoard)
    memory_snapshot: dict[str, str] = {}
    stages: list[StageState] = []
    artifacts: dict[str, Any] = {}  # stage_id -> structured output
    assets: list[AssetRef] = []
    memory_diff: list[MemoryChange] = []
    strategy_answer: str | None = None


# ── WebSocket protocol (/api/sessions/{id}/ws) ──────────────────────────────
# Client → server

class RepUtterance(BaseModel):
    type: Literal["rep_utterance"] = "rep_utterance"
    text: str = Field(min_length=1, max_length=4000)


class EndInterview(BaseModel):
    type: Literal["end_interview"] = "end_interview"


class StartBuild(BaseModel):
    type: Literal["start_build"] = "start_build"


# Server → client

class MemoriaDelta(BaseModel):
    type: Literal["memoria_delta"] = "memoria_delta"
    text: str


class MemoriaSentence(BaseModel):
    """A complete sentence, ready for TTS. index counts sentences within the turn."""
    type: Literal["memoria_sentence"] = "memoria_sentence"
    index: int
    text: str


class MemoriaTurnDone(BaseModel):
    type: Literal["memoria_turn_done"] = "memoria_turn_done"
    text: str


class SlotsChanged(BaseModel):
    type: Literal["slots_changed"] = "slots_changed"
    updates: list[SlotUpdate]
    board: SlotBoard


class InterviewComplete(BaseModel):
    type: Literal["interview_complete"] = "interview_complete"
    reason: Literal["slots_filled", "rep_ended", "turn_limit"]


class StageEvent(BaseModel):
    type: Literal["stage"] = "stage"
    stage: StageState


class AssetReady(BaseModel):
    type: Literal["asset_ready"] = "asset_ready"
    asset: AssetRef


class MemoryDiffReady(BaseModel):
    type: Literal["memory_diff"] = "memory_diff"
    changes: list[MemoryChange]


class StrategyAnswerReady(BaseModel):
    type: Literal["strategy_answer"] = "strategy_answer"
    text: str


class BuildComplete(BaseModel):
    type: Literal["build_complete"] = "build_complete"


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str
    recoverable: bool = True


Tenant.model_rebuild()
