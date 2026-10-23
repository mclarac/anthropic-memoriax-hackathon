/**
 * TypeScript mirror of backend/src/memoria/models.py and docs/contract.md.
 *
 * Changing a model there changes the wire format. Update this file in the same change.
 */

export const ASSET_TYPES = ["deck", "document", "blog", "email_sequence", "whitepaper"] as const;
export type AssetType = (typeof ASSET_TYPES)[number];

export const SLOT_STATUSES = ["confirmed", "rep_unsure", "open", "conflict"] as const;
export type SlotStatus = (typeof SLOT_STATUSES)[number];

export const STAGE_IDS = [
  "deal_brief",
  "retrieval",
  "research",
  "personas",
  "strategy",
  "assets",
  "verifier",
  "memory_writer",
  "strategy_answer",
] as const;
export type StageId = (typeof STAGE_IDS)[number];

export const STAGE_STATUSES = ["pending", "running", "done", "failed", "skipped"] as const;
export type StageStatus = (typeof STAGE_STATUSES)[number];

export type SessionPhase = "interview" | "building" | "complete" | "failed";

export const FILE_FORMATS = ["pptx", "docx", "pdf", "md", "html", "eml"] as const;
export type FileFormat = (typeof FILE_FORMATS)[number];

export const INTERVIEW_END_REASONS = ["slots_filled", "rep_ended", "turn_limit"] as const;
export type InterviewEndReason = (typeof INTERVIEW_END_REASONS)[number];

export const SLOT_GROUPS = [
  { label: "Deal", slots: ["next_meeting", "win_condition", "deadline"] },
  { label: "Pain", slots: ["pain", "metrics"] },
  {
    label: "Decision",
    slots: ["decision_process", "economic_buyer", "decision_criteria", "paper_process", "champion"],
  },
  { label: "Risk", slots: ["objections", "competition"] },
  {
    label: "Campaign",
    slots: ["assets_requested", "audience", "brand_constraints", "forbidden_claims"],
  },
] as const;

export const SLOT_NAMES: readonly string[] = SLOT_GROUPS.flatMap((g) => g.slots);

// Same pattern as SessionCreate.account_slug and rep_slug.
const SLUG_PATTERN = /^[a-z0-9][a-z0-9-]{0,62}$/;

export function isValidSlug(value: string): boolean {
  return SLUG_PATTERN.test(value);
}

export interface TenantProfile {
  name: string;
  offering_summary: string;
  brand_voice: string;
  approved_claims: string[];
  forbidden_claims: string[];
  default_assets: AssetType[];
}

export interface DocumentRef {
  id: string;
  filename: string;
  media_type: string;
  size_bytes: number;
  scope: "tenant" | "account";
  account_slug: string | null;
}

export interface Tenant {
  id: string;
  profile: TenantProfile;
  memory_store_id: string | null;
  documents: DocumentRef[];
}

export interface Slot {
  value: string | null;
  status: SlotStatus;
  evidence_quote: string | null;
  conflicts_with: string | null;
  needs_spelling_check: boolean;
}

export interface SlotBoard {
  slots: Record<string, Slot>;
}

export interface SlotUpdate {
  slot: string;
  value: string | null;
  status: "confirmed" | "rep_unsure" | "conflict";
  evidence_quote: string;
  conflicts_with: string | null;
  needs_spelling_check: boolean;
}

export interface Turn {
  speaker: "memoria" | "rep";
  text: string;
}

export interface StageState {
  stage_id: StageId;
  status: StageStatus;
  detail: string | null;
  duration_ms: number | null;
}

export interface RenderedFile {
  format: FileFormat;
  url: string;
  size_bytes: number;
}

export interface AssetRef {
  asset_type: AssetType;
  title: string;
  verdict: "pass" | "needs_human_review";
  placeholders: string[];
  files: RenderedFile[];
}

export interface MemoryChange {
  path: string;
  change: "added" | "modified" | "removed";
  before: string | null;
  after: string | null;
}

export interface SessionCreate {
  tenant_id: string;
  account_slug: string;
  rep_slug: string;
}

export interface Session {
  id: string;
  tenant_id: string;
  account_slug: string;
  rep_slug: string;
  phase: SessionPhase;
  turns: Turn[];
  board: SlotBoard;
  memory_snapshot: Record<string, string>;
  stages: StageState[];
  assets: AssetRef[];
  memory_diff: MemoryChange[];
  strategy_answer: string | null;
}

// Client -> server

export type ClientMessage =
  | { type: "rep_utterance"; text: string }
  | { type: "end_interview" }
  | { type: "start_build" };

// Server -> client

export type ServerEvent =
  | { type: "memoria_delta"; text: string }
  | { type: "memoria_sentence"; index: number; text: string }
  | { type: "memoria_turn_done"; text: string }
  | { type: "slots_changed"; updates: SlotUpdate[]; board: SlotBoard }
  | { type: "interview_complete"; reason: InterviewEndReason }
  | { type: "stage"; stage: StageState }
  | { type: "asset_ready"; asset: AssetRef }
  | { type: "memory_diff"; changes: MemoryChange[] }
  | { type: "strategy_answer"; text: string }
  | { type: "build_complete" }
  | { type: "error"; message: string; recoverable: boolean };

export type ParseResult = { ok: true; event: ServerEvent } | { ok: false; error: string };

type Json = Record<string, unknown>;

class ShapeError extends Error {}

function isRecord(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function record(value: unknown, what: string): Json {
  if (!isRecord(value)) throw new ShapeError(`${what} must be an object`);
  return value;
}

function str(value: unknown, what: string): string {
  if (typeof value !== "string") throw new ShapeError(`${what} must be a string`);
  return value;
}

function nullableStr(value: unknown, what: string): string | null {
  if (value === undefined || value === null) return null;
  return str(value, what);
}

function bool(value: unknown, what: string, fallback: boolean): boolean {
  if (value === undefined) return fallback;
  if (typeof value !== "boolean") throw new ShapeError(`${what} must be a boolean`);
  return value;
}

function nonNegativeInt(value: unknown, what: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new ShapeError(`${what} must be a non-negative integer`);
  }
  return value;
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[], what: string): T {
  if (typeof value !== "string" || !allowed.includes(value as T)) {
    throw new ShapeError(`${what} must be one of ${allowed.join(", ")}`);
  }
  return value as T;
}

function list<T>(value: unknown, what: string, item: (v: unknown, i: number) => T): T[] {
  if (value === undefined) return [];
  if (!Array.isArray(value)) throw new ShapeError(`${what} must be an array`);
  return value.map(item);
}

function slot(value: unknown, what: string): Slot {
  const s = record(value, what);
  return {
    value: nullableStr(s.value, `${what}.value`),
    status: oneOf(s.status ?? "open", SLOT_STATUSES, `${what}.status`),
    evidence_quote: nullableStr(s.evidence_quote, `${what}.evidence_quote`),
    conflicts_with: nullableStr(s.conflicts_with, `${what}.conflicts_with`),
    needs_spelling_check: bool(s.needs_spelling_check, `${what}.needs_spelling_check`, false),
  };
}

export function parseSlotBoard(value: unknown): SlotBoard {
  const raw = record(record(value, "board").slots, "board.slots");
  const slots: Record<string, Slot> = {};
  for (const name of SLOT_NAMES) slots[name] = slot(raw[name] ?? {}, `board.slots.${name}`);
  for (const name of Object.keys(raw)) {
    if (!(name in slots)) slots[name] = slot(raw[name], `board.slots.${name}`);
  }
  return { slots };
}

function slotUpdate(value: unknown, i: number): SlotUpdate {
  const what = `updates[${i}]`;
  const u = record(value, what);
  return {
    slot: str(u.slot, `${what}.slot`),
    value: nullableStr(u.value, `${what}.value`),
    status: oneOf(u.status, ["confirmed", "rep_unsure", "conflict"] as const, `${what}.status`),
    evidence_quote: str(u.evidence_quote, `${what}.evidence_quote`),
    conflicts_with: nullableStr(u.conflicts_with, `${what}.conflicts_with`),
    needs_spelling_check: bool(u.needs_spelling_check, `${what}.needs_spelling_check`, false),
  };
}

export function parseStageState(value: unknown): StageState {
  const s = record(value, "stage");
  const duration = s.duration_ms;
  if (duration !== undefined && duration !== null) nonNegativeInt(duration, "stage.duration_ms");
  return {
    stage_id: oneOf(s.stage_id, STAGE_IDS, "stage.stage_id"),
    status: oneOf(s.status ?? "pending", STAGE_STATUSES, "stage.status"),
    detail: nullableStr(s.detail, "stage.detail"),
    duration_ms: (duration as number | null | undefined) ?? null,
  };
}

export function parseAssetRef(value: unknown): AssetRef {
  const a = record(value, "asset");
  return {
    asset_type: oneOf(a.asset_type, ASSET_TYPES, "asset.asset_type"),
    title: str(a.title, "asset.title"),
    verdict: oneOf(a.verdict, ["pass", "needs_human_review"] as const, "asset.verdict"),
    placeholders: list(a.placeholders, "asset.placeholders", (p) => str(p, "placeholder")),
    files: list(a.files, "asset.files", (f) => {
      const file = record(f, "file");
      return {
        format: oneOf(file.format, FILE_FORMATS, "file.format"),
        url: str(file.url, "file.url"),
        size_bytes: nonNegativeInt(file.size_bytes, "file.size_bytes"),
      };
    }),
  };
}

export function parseMemoryChange(value: unknown): MemoryChange {
  const c = record(value, "change");
  return {
    path: str(c.path, "change.path"),
    change: oneOf(c.change, ["added", "modified", "removed"] as const, "change.change"),
    before: nullableStr(c.before, "change.before"),
    after: nullableStr(c.after, "change.after"),
  };
}

function buildEvent(raw: Json): ServerEvent {
  const type = raw.type;
  switch (type) {
    case "memoria_delta":
      return { type, text: str(raw.text, "text") };
    case "memoria_sentence":
      return { type, index: nonNegativeInt(raw.index, "index"), text: str(raw.text, "text") };
    case "memoria_turn_done":
      return { type, text: str(raw.text, "text") };
    case "slots_changed":
      return {
        type,
        updates: list(raw.updates, "updates", slotUpdate),
        board: parseSlotBoard(raw.board),
      };
    case "interview_complete":
      return { type, reason: oneOf(raw.reason, INTERVIEW_END_REASONS, "reason") };
    case "stage":
      return { type, stage: parseStageState(raw.stage) };
    case "asset_ready":
      return { type, asset: parseAssetRef(raw.asset) };
    case "memory_diff":
      return { type, changes: list(raw.changes, "changes", parseMemoryChange) };
    case "strategy_answer":
      return { type, text: str(raw.text, "text") };
    case "build_complete":
      return { type };
    case "error":
      return {
        type,
        message: str(raw.message, "message"),
        recoverable: bool(raw.recoverable, "recoverable", true),
      };
    default:
      throw new ShapeError(`Unknown event type "${String(type)}"`);
  }
}

/** Validates one WebSocket frame. Unknown or malformed frames are reported, never guessed at. */
export function parseServerEvent(frame: string): ParseResult {
  let raw: unknown;
  try {
    raw = JSON.parse(frame);
  } catch {
    return { ok: false, error: "Frame is not valid JSON" };
  }
  if (!isRecord(raw)) return { ok: false, error: "Frame must be a JSON object" };
  try {
    return { ok: true, event: buildEvent(raw) };
  } catch (error) {
    if (error instanceof ShapeError) return { ok: false, error: error.message };
    throw error;
  }
}
