import {
  SLOT_NAMES,
  STAGE_IDS,
  type AssetRef,
  type InterviewEndReason,
  type MemoryChange,
  type ServerEvent,
  type Session,
  type SessionPhase,
  type SlotBoard,
  type StageState,
  type Turn,
} from "../contract";

export type ConnectionStatus = "connecting" | "open" | "closed";

export interface SessionError {
  message: string;
  recoverable: boolean;
}

export interface SessionState {
  connection: ConnectionStatus;
  phase: SessionPhase;
  turns: Turn[];
  /** Memoria's turn while it is still streaming in. */
  streaming: string | null;
  memoriaTurnCount: number;
  board: SlotBoard;
  recentlyChanged: string[];
  interviewEnded: InterviewEndReason | null;
  /** The rep asked to build before the server declared the interview over. */
  buildRequested: boolean;
  stages: StageState[];
  assets: AssetRef[];
  memoryDiff: MemoryChange[] | null;
  strategyAnswer: string | null;
  error: SessionError | null;
}

export type SessionAction =
  | ServerEvent
  | { type: "rep_sent"; text: string }
  | { type: "build_requested" }
  | { type: "build_started" }
  | { type: "connection"; status: ConnectionStatus }
  | { type: "hydrate"; session: Session };

function emptyBoard(): SlotBoard {
  return {
    slots: Object.fromEntries(
      SLOT_NAMES.map((name) => [
        name,
        { value: null, status: "open", evidence_quote: null, conflicts_with: null, needs_spelling_check: false },
      ]),
    ),
  };
}

function pendingStages(): StageState[] {
  return STAGE_IDS.map((stage_id) => ({ stage_id, status: "pending", detail: null, duration_ms: null }));
}

export function initialSessionState(): SessionState {
  return {
    connection: "connecting",
    phase: "interview",
    turns: [],
    streaming: null,
    memoriaTurnCount: 0,
    board: emptyBoard(),
    recentlyChanged: [],
    interviewEnded: null,
    buildRequested: false,
    stages: pendingStages(),
    assets: [],
    memoryDiff: null,
    strategyAnswer: null,
    error: null,
  };
}

/** Slots the rep has answered, including "I don't know", which is still an answer. */
export function filledSlotCount(board: SlotBoard): number {
  return Object.values(board.slots).filter((s) => s.status === "confirmed" || s.status === "rep_unsure").length;
}

function mergeStages(received: StageState[]): StageState[] {
  return pendingStages().map((pending) => received.find((s) => s.stage_id === pending.stage_id) ?? pending);
}

function upsertAsset(assets: AssetRef[], asset: AssetRef): AssetRef[] {
  const at = assets.findIndex((a) => a.asset_type === asset.asset_type && a.title === asset.title);
  if (at === -1) return [...assets, asset];
  return assets.map((a, i) => (i === at ? asset : a));
}

export function sessionReducer(state: SessionState, action: SessionAction): SessionState {
  switch (action.type) {
    case "memoria_delta":
      return { ...state, streaming: (state.streaming ?? "") + action.text };
    case "memoria_sentence":
      return state;
    case "memoria_turn_done":
      return {
        ...state,
        streaming: null,
        turns: [...state.turns, { speaker: "memoria", text: action.text }],
        memoriaTurnCount: state.memoriaTurnCount + 1,
      };
    case "rep_sent":
      return { ...state, turns: [...state.turns, { speaker: "rep", text: action.text }], error: null };
    case "slots_changed":
      return { ...state, board: action.board, recentlyChanged: action.updates.map((u) => u.slot) };
    case "interview_complete":
      return { ...state, interviewEnded: action.reason };
    case "build_requested":
      return { ...state, buildRequested: true };
    case "build_started":
      return { ...state, phase: "building", buildRequested: false };
    case "stage": {
      const phase = state.phase === "interview" ? "building" : state.phase;
      const stages = state.stages.map((s) => (s.stage_id === action.stage.stage_id ? action.stage : s));
      return { ...state, phase, stages };
    }
    case "asset_ready":
      return { ...state, assets: upsertAsset(state.assets, action.asset) };
    case "memory_diff":
      return { ...state, memoryDiff: action.changes };
    case "strategy_answer":
      return { ...state, strategyAnswer: action.text };
    case "build_complete":
      return state.phase === "failed" ? state : { ...state, phase: "complete" };
    case "error":
      return {
        ...state,
        streaming: null,
        phase: action.recoverable ? state.phase : "failed",
        error: { message: action.message, recoverable: action.recoverable },
      };
    case "connection":
      return { ...state, connection: action.status };
    case "hydrate": {
      const { session } = action;
      return {
        ...state,
        phase: session.phase,
        turns: session.turns,
        streaming: null,
        memoriaTurnCount: session.turns.filter((t) => t.speaker === "memoria").length,
        board: session.board,
        stages: mergeStages(session.stages),
        assets: session.assets,
        memoryDiff: session.memory_diff.length > 0 ? session.memory_diff : null,
        strategyAnswer: session.strategy_answer,
      };
    }
  }
}
