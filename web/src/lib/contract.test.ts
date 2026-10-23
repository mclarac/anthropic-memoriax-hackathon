import { describe, expect, it } from "vitest";
import {
  ASSET_TYPES,
  SLOT_GROUPS,
  SLOT_NAMES,
  isValidSlug,
  parseServerEvent,
} from "./contract";

const board = Object.fromEntries(
  SLOT_NAMES.map((name) => [name, { value: null, status: "open", evidence_quote: null, conflicts_with: null, needs_spelling_check: false }]),
);

describe("slot constants", () => {
  it("groups all 16 slots exactly once", () => {
    const grouped = SLOT_GROUPS.flatMap((g) => g.slots);
    expect(grouped).toHaveLength(16);
    expect(new Set(grouped)).toEqual(new Set(SLOT_NAMES));
  });

  it("lists the five asset types", () => {
    expect(ASSET_TYPES).toEqual(["deck", "document", "blog", "email_sequence", "whitepaper"]);
  });
});

describe("isValidSlug", () => {
  it.each(["acme", "acme-corp", "a", "0day", "a".repeat(63)])("accepts %s", (slug) => {
    expect(isValidSlug(slug)).toBe(true);
  });

  it.each(["", "Acme", "-acme", "acme corp", "acme_corp", "a".repeat(64), "acme\n", "émile"])(
    "rejects %j",
    (slug) => {
      expect(isValidSlug(slug)).toBe(false);
    },
  );
});

describe("parseServerEvent", () => {
  it("parses a delta from a JSON string", () => {
    const result = parseServerEvent(JSON.stringify({ type: "memoria_delta", text: "Hi" }));
    expect(result).toEqual({ ok: true, event: { type: "memoria_delta", text: "Hi" } });
  });

  it("parses a sentence with its index", () => {
    const result = parseServerEvent('{"type":"memoria_sentence","index":2,"text":"Hello."}');
    expect(result).toEqual({ ok: true, event: { type: "memoria_sentence", index: 2, text: "Hello." } });
  });

  it("parses slots_changed with updates and a full board", () => {
    const raw = {
      type: "slots_changed",
      updates: [{ slot: "pain", value: "slow quotes", status: "confirmed", evidence_quote: "quotes are slow", conflicts_with: null, needs_spelling_check: false }],
      board: { slots: board },
    };
    const result = parseServerEvent(JSON.stringify(raw));
    expect(result.ok).toBe(true);
  });

  it("parses stage, asset_ready, memory_diff, strategy_answer, build_complete, interview_complete and error", () => {
    const events = [
      { type: "stage", stage: { stage_id: "retrieval", status: "running", detail: null, duration_ms: null } },
      { type: "asset_ready", asset: { asset_type: "deck", title: "Deck", verdict: "pass", placeholders: [], files: [{ format: "pptx", url: "/api/files/s/d.pptx", size_bytes: 10 }] } },
      { type: "memory_diff", changes: [{ path: "/a.md", change: "added", before: null, after: "x" }] },
      { type: "strategy_answer", text: "Lead with cost." },
      { type: "build_complete" },
      { type: "interview_complete", reason: "slots_filled" },
      { type: "error", message: "boom", recoverable: false },
      { type: "memoria_turn_done", text: "Done." },
    ];
    for (const event of events) {
      expect(parseServerEvent(JSON.stringify(event))).toEqual({ ok: true, event });
    }
  });

  it("defaults error.recoverable to true as the server model does", () => {
    const result = parseServerEvent('{"type":"error","message":"slow"}');
    expect(result).toEqual({ ok: true, event: { type: "error", message: "slow", recoverable: true } });
  });

  it("rejects text that is not JSON", () => {
    const result = parseServerEvent("not json");
    expect(result.ok).toBe(false);
  });

  it("rejects an unknown type", () => {
    const result = parseServerEvent('{"type":"telepathy"}');
    expect(result).toEqual({ ok: false, error: 'Unknown event type "telepathy"' });
  });

  it("rejects a non-object payload", () => {
    expect(parseServerEvent("[1]").ok).toBe(false);
    expect(parseServerEvent("null").ok).toBe(false);
  });

  it.each([
    ["delta without text", { type: "memoria_delta" }],
    ["sentence with a string index", { type: "memoria_sentence", index: "1", text: "x" }],
    ["sentence with a negative index", { type: "memoria_sentence", index: -1, text: "x" }],
    ["interview_complete with bad reason", { type: "interview_complete", reason: "bored" }],
    ["stage with unknown stage id", { type: "stage", stage: { stage_id: "magic", status: "done" } }],
    ["stage with unknown status", { type: "stage", stage: { stage_id: "research", status: "sleeping" } }],
    ["asset with unknown verdict", { type: "asset_ready", asset: { asset_type: "deck", title: "t", verdict: "meh", placeholders: [], files: [] } }],
    ["asset with unknown file format", { type: "asset_ready", asset: { asset_type: "deck", title: "t", verdict: "pass", placeholders: [], files: [{ format: "exe", url: "u", size_bytes: 1 }] } }],
    ["memory_diff with unknown change", { type: "memory_diff", changes: [{ path: "/a", change: "teleported" }] }],
    ["slots_changed with no board", { type: "slots_changed", updates: [] }],
    ["slots_changed with an unknown slot status", { type: "slots_changed", updates: [], board: { slots: { pain: { status: "maybe" } } } }],
  ])("rejects %s", (_label, payload) => {
    expect(parseServerEvent(JSON.stringify(payload)).ok).toBe(false);
  });

  it("fills missing optional fields of a slot update", () => {
    const raw = {
      type: "slots_changed",
      updates: [{ slot: "pain", value: null, status: "rep_unsure", evidence_quote: "not sure" }],
      board: { slots: { pain: { status: "rep_unsure" } } },
    };
    const result = parseServerEvent(JSON.stringify(raw));
    expect(result.ok).toBe(true);
    if (result.ok && result.event.type === "slots_changed") {
      expect(result.event.updates[0]).toEqual({ slot: "pain", value: null, status: "rep_unsure", evidence_quote: "not sure", conflicts_with: null, needs_spelling_check: false });
      expect(result.event.board.slots.pain).toEqual({ value: null, status: "rep_unsure", evidence_quote: null, conflicts_with: null, needs_spelling_check: false });
    }
  });
});
