import { describe, expect, it } from "vitest";
import type { AssetRef, ServerEvent, Session, SlotBoard, StageState } from "../contract";
import { SLOT_NAMES, STAGE_IDS } from "../contract";
import { filledSlotCount, initialSessionState, sessionReducer, type SessionAction, type SessionState } from "./reducer";

function run(actions: SessionAction[], from: SessionState = initialSessionState()): SessionState {
  return actions.reduce(sessionReducer, from);
}

const open = { value: null, status: "open", evidence_quote: null, conflicts_with: null, needs_spelling_check: false } as const;

function board(filled: Record<string, Partial<SlotBoard["slots"][string]>> = {}): SlotBoard {
  return {
    slots: Object.fromEntries(
      SLOT_NAMES.map((name) => [name, { ...open, ...(filled[name] ?? {}) }]),
    ),
  };
}

const confirmed = (value: string) => ({ value, status: "confirmed" as const, evidence_quote: `said ${value}` });

function stage(stage_id: StageState["stage_id"], status: StageState["status"], duration_ms: number | null = null): ServerEvent {
  return { type: "stage", stage: { stage_id, status, detail: null, duration_ms } };
}

const deck: AssetRef = { asset_type: "deck", title: "Deck", verdict: "pass", placeholders: [], files: [] };

describe("initial state", () => {
  it("starts connecting, in the interview phase, with 16 open slots and 9 pending stages", () => {
    const state = initialSessionState();
    expect(state.connection).toBe("connecting");
    expect(state.phase).toBe("interview");
    expect(Object.keys(state.board.slots)).toHaveLength(16);
    expect(filledSlotCount(state.board)).toBe(0);
    expect(state.stages.map((s) => s.stage_id)).toEqual([...STAGE_IDS]);
    expect(state.stages.every((s) => s.status === "pending")).toBe(true);
  });
});

describe("memoria turns", () => {
  it("accumulates deltas into the streaming turn and commits it on turn_done", () => {
    let state = run([
      { type: "memoria_delta", text: "Hello " },
      { type: "memoria_delta", text: "there." },
    ]);
    expect(state.streaming).toBe("Hello there.");
    expect(state.turns).toEqual([]);

    state = sessionReducer(state, { type: "memoria_turn_done", text: "Hello there." });
    expect(state.streaming).toBeNull();
    expect(state.turns).toEqual([{ speaker: "memoria", text: "Hello there." }]);
  });

  it("uses the full turn text from turn_done over the accumulated deltas", () => {
    const state = run([
      { type: "memoria_delta", text: "Hel" },
      { type: "memoria_turn_done", text: "Hello." },
    ]);
    expect(state.turns).toEqual([{ speaker: "memoria", text: "Hello." }]);
  });

  it("counts completed memoria turns so playback can key sentences by turn", () => {
    const state = run([
      { type: "memoria_turn_done", text: "One." },
      { type: "memoria_turn_done", text: "Two." },
    ]);
    expect(state.memoriaTurnCount).toBe(2);
  });

  it("ignores memoria_sentence, which only drives audio", () => {
    const before = initialSessionState();
    expect(sessionReducer(before, { type: "memoria_sentence", index: 0, text: "Hi." })).toBe(before);
  });

  it("appends the rep's utterance as a turn", () => {
    const state = run([{ type: "rep_sent", text: "We sell widgets" }]);
    expect(state.turns).toEqual([{ speaker: "rep", text: "We sell widgets" }]);
  });
});

describe("slots", () => {
  it("replaces the board and records which slots just changed", () => {
    const state = run([
      {
        type: "slots_changed",
        updates: [{ slot: "pain", value: "slow", status: "confirmed", evidence_quote: "so slow", conflicts_with: null, needs_spelling_check: false }],
        board: board({ pain: confirmed("slow") }),
      },
    ]);
    expect(state.board.slots.pain.value).toBe("slow");
    expect(filledSlotCount(state.board)).toBe(1);
    expect(state.recentlyChanged).toEqual(["pain"]);
  });

  it("handles slots_changed arriving before the memoria turn finishes", () => {
    const state = run([
      { type: "memoria_delta", text: "Got it. " },
      {
        type: "slots_changed",
        updates: [],
        board: board({ champion: confirmed("Dana") }),
      },
      { type: "memoria_turn_done", text: "Got it. Who else?" },
    ]);
    expect(state.board.slots.champion.value).toBe("Dana");
    expect(state.turns).toEqual([{ speaker: "memoria", text: "Got it. Who else?" }]);
    expect(state.streaming).toBeNull();
  });

  it("keeps the latest board when updates arrive in successive events", () => {
    const state = run([
      { type: "slots_changed", updates: [], board: board({ pain: confirmed("a") }) },
      { type: "slots_changed", updates: [], board: board({ pain: confirmed("a"), metrics: confirmed("b") }) },
    ]);
    expect(filledSlotCount(state.board)).toBe(2);
  });

  it("counts confirmed and unsure slots as filled but not conflicts or open ones", () => {
    const b = board({
      pain: confirmed("x"),
      metrics: { status: "rep_unsure" },
      champion: { status: "conflict", value: "A", conflicts_with: "B" },
    });
    expect(filledSlotCount(b)).toBe(2);
  });
});

describe("interview and build lifecycle", () => {
  it("records why the interview ended", () => {
    const state = run([{ type: "interview_complete", reason: "slots_filled" }]);
    expect(state.interviewEnded).toBe("slots_filled");
    expect(state.phase).toBe("interview");
  });

  it("enters the building phase when the build starts", () => {
    const state = run([{ type: "interview_complete", reason: "rep_ended" }, { type: "build_started" }]);
    expect(state.phase).toBe("building");
  });

  it("remembers a build request made before the interview ended", () => {
    const state = run([{ type: "build_requested" }]);
    expect(state.buildRequested).toBe(true);
    expect(state.phase).toBe("interview");
  });

  it("updates stages in place, keeping chain order and recording durations", () => {
    const state = run([
      { type: "build_started" },
      stage("deal_brief", "running"),
      stage("deal_brief", "done", 1200),
      stage("retrieval", "running"),
    ]);
    expect(state.stages.map((s) => s.stage_id)).toEqual([...STAGE_IDS]);
    expect(state.stages[0]).toMatchObject({ status: "done", duration_ms: 1200 });
    expect(state.stages[1].status).toBe("running");
    expect(state.stages[2].status).toBe("pending");
  });

  it("treats a stage event as proof the build is running (page reloaded mid-build)", () => {
    expect(run([stage("research", "running")]).phase).toBe("building");
  });

  it("collects assets, replacing one of the same type and title", () => {
    const state = run([
      { type: "asset_ready", asset: deck },
      { type: "asset_ready", asset: { ...deck, title: "Email", asset_type: "email_sequence" } },
      { type: "asset_ready", asset: { ...deck, verdict: "needs_human_review" } },
    ]);
    expect(state.assets).toHaveLength(2);
    expect(state.assets[0].verdict).toBe("needs_human_review");
  });

  it("stores the memory diff and strategy answer", () => {
    const state = run([
      { type: "memory_diff", changes: [{ path: "/a.md", change: "added", before: null, after: "x" }] },
      { type: "strategy_answer", text: "Lead with cost." },
    ]);
    expect(state.memoryDiff).toHaveLength(1);
    expect(state.strategyAnswer).toBe("Lead with cost.");
  });

  it("completes on build_complete", () => {
    const state = run([{ type: "build_started" }, { type: "build_complete" }]);
    expect(state.phase).toBe("complete");
  });
});

describe("failures", () => {
  it("fails the build on an unrecoverable error and keeps what was produced", () => {
    const state = run([
      { type: "build_started" },
      { type: "asset_ready", asset: deck },
      stage("verifier", "failed"),
      { type: "error", message: "Verifier crashed", recoverable: false },
    ]);
    expect(state.phase).toBe("failed");
    expect(state.assets).toHaveLength(1);
    expect(state.stages.find((s) => s.stage_id === "verifier")?.status).toBe("failed");
    expect(state.error).toEqual({ message: "Verifier crashed", recoverable: false });
  });

  it("does not turn a later build_complete into success after a failure", () => {
    const state = run([
      { type: "build_started" },
      { type: "error", message: "nope", recoverable: false },
      { type: "build_complete" },
    ]);
    expect(state.phase).toBe("failed");
  });

  it("keeps the phase on a recoverable error but surfaces the message", () => {
    const state = run([{ type: "error", message: "Turn failed, try again", recoverable: true }]);
    expect(state.phase).toBe("interview");
    expect(state.error).toEqual({ message: "Turn failed, try again", recoverable: true });
  });

  it("clears the error when the rep tries again", () => {
    const state = run([
      { type: "error", message: "x", recoverable: true },
      { type: "rep_sent", text: "retry" },
    ]);
    expect(state.error).toBeNull();
  });

  it("drops a half-streamed turn when a recoverable error interrupts it", () => {
    const state = run([
      { type: "memoria_delta", text: "Partial" },
      { type: "error", message: "x", recoverable: true },
    ]);
    expect(state.streaming).toBeNull();
  });
});

describe("connection and hydration", () => {
  it("tracks connection status", () => {
    expect(run([{ type: "connection", status: "open" }]).connection).toBe("open");
    expect(run([{ type: "connection", status: "closed" }]).connection).toBe("closed");
  });

  it("restores a server session snapshot", () => {
    const session: Session = {
      id: "s1",
      tenant_id: "t1",
      account_slug: "acme",
      rep_slug: "sam",
      phase: "building",
      turns: [{ speaker: "memoria", text: "Hi" }, { speaker: "rep", text: "Hello" }],
      board: board({ pain: confirmed("slow") }),
      memory_snapshot: {},
      stages: [{ stage_id: "deal_brief", status: "done", detail: null, duration_ms: 5 }],
      assets: [deck],
      memory_diff: [],
      strategy_answer: "Answer",
    };
    const state = run([{ type: "hydrate", session }]);
    expect(state.phase).toBe("building");
    expect(state.turns).toHaveLength(2);
    expect(state.memoriaTurnCount).toBe(1);
    expect(state.board.slots.pain.value).toBe("slow");
    expect(state.stages).toHaveLength(9);
    expect(state.stages[0].status).toBe("done");
    expect(state.stages[1].status).toBe("pending");
    expect(state.assets).toEqual([deck]);
    expect(state.strategyAnswer).toBe("Answer");
    expect(state.memoryDiff).toBeNull();
  });
});
