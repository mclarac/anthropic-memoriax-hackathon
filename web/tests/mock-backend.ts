/**
 * A contract-faithful stand-in for the Memoria API, used by the Playwright suite.
 * It follows docs/contract.md "Fake mode behavior": the opening turn on connect,
 * one slot confirmed per typed answer, interview_complete after the 6th answer,
 * stage events in chain order, five assets, a memory diff, a strategy answer and
 * build_complete last.
 *
 * Test-only controls live under /__mock and are not part of the contract.
 */
import { randomUUID } from "node:crypto";
import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import { pathToFileURL } from "node:url";
import { WebSocketServer, type WebSocket } from "ws";

const SLOT_ORDER = [
  "next_meeting",
  "win_condition",
  "pain",
  "metrics",
  "decision_process",
  "economic_buyer",
  "decision_criteria",
  "objections",
  "competition",
  "champion",
  "paper_process",
  "assets_requested",
  "audience",
  "deadline",
  "brand_constraints",
  "forbidden_claims",
];

const QUESTIONS = [
  "What is the next meeting with this account, and when is it?",
  "What would a win look like for you on this deal?",
  "What pain is the buyer trying to get rid of?",
  "Which numbers will the buyer judge success by?",
  "Walk me through how they decide.",
  "Who holds the budget?",
];

const STAGES = [
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

const STAGE_DURATIONS_MS = [1200, 3400, 9100, 2300, 4100, 6700, 1800, 2600, 900];
const ANSWERS_BEFORE_COMPLETE = 6;
const SLUG = /^[a-z0-9][a-z0-9-]{0,62}$/;
const ALLOWED_UPLOADS = [".pdf", ".docx", ".md", ".txt"];
const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;

type Json = Record<string, unknown>;
type Slot = { value: string | null; status: string; evidence_quote: string | null; conflicts_with: string | null; needs_spelling_check: boolean };

interface TenantRecord {
  id: string;
  profile: Json;
  memory_store_id: string | null;
  documents: Json[];
}

interface SessionRecord {
  id: string;
  tenant_id: string;
  account_slug: string;
  rep_slug: string;
  phase: string;
  turns: { speaker: "memoria" | "rep"; text: string }[];
  board: { slots: Record<string, Slot> };
  memory_snapshot: Record<string, string>;
  stages: Json[];
  artifacts: Json;
  assets: Json[];
  memory_diff: Json[];
  strategy_answer: string | null;
  answers: number;
  complete: boolean;
  building: boolean;
  openingSent: boolean;
}

export interface MockOptions {
  stageDelayMs?: number;
}

function emptyBoard() {
  return {
    slots: Object.fromEntries(
      SLOT_ORDER.map((name) => [name, { value: null, status: "open", evidence_quote: null, conflicts_with: null, needs_spelling_check: false }]),
    ),
  };
}

function silentWav(seconds = 0.2, rate = 24000): Buffer {
  const samples = Math.round(seconds * rate);
  const data = samples * 2;
  const header = Buffer.alloc(44);
  header.write("RIFF", 0);
  header.writeUInt32LE(36 + data, 4);
  header.write("WAVEfmt ", 8);
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20);
  header.writeUInt16LE(1, 22);
  header.writeUInt32LE(rate, 24);
  header.writeUInt32LE(rate * 2, 28);
  header.writeUInt16LE(2, 32);
  header.writeUInt16LE(16, 34);
  header.write("data", 36);
  header.writeUInt32LE(data, 40);
  return Buffer.concat([header, Buffer.alloc(data)]);
}

const CONTENT_TYPES: Record<string, string> = {
  pptx: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  pdf: "application/pdf",
  md: "text/markdown; charset=utf-8",
  html: "text/html; charset=utf-8",
  eml: "message/rfc822",
};

function assetFixtures(sessionId: string) {
  const file = (name: string, size: number) => ({
    format: name.split(".").pop(),
    url: `/api/files/${sessionId}/${name}`,
    size_bytes: size,
  });
  return [
    { asset_type: "deck", title: "Northwind renewal deck", verdict: "pass", placeholders: [], files: [file("deck.pptx", 184_320), file("deck.pdf", 96_256)] },
    { asset_type: "document", title: "One-page account plan", verdict: "pass", placeholders: [], files: [file("document.docx", 24_576), file("document.pdf", 41_984)] },
    { asset_type: "blog", title: "Why dwell time is the metric that matters", verdict: "needs_human_review", placeholders: ["[CUSTOMER QUOTE]", "[Q3 BENCHMARK]"], files: [file("blog.md", 5_120), file("blog.html", 7_168)] },
    { asset_type: "email_sequence", title: "Three-touch follow-up sequence", verdict: "pass", placeholders: [], files: [file("email_sequence.eml", 3_072)] },
    { asset_type: "whitepaper", title: "Reducing yard congestion without new headcount", verdict: "pass", placeholders: [], files: [file("whitepaper.pdf", 312_320), file("whitepaper.docx", 58_368)] },
  ];
}

const STRATEGY_ANSWER = `## Lead with dwell time, not features

The buyer's pain is **slow yard turnaround** [E2]. Open with the metric they already track, then show the three-step path to improve it.

1. Confirm the baseline with the economic buyer.
2. Show the pilot result from a comparable account [E5].
3. Offer a 30-day pilot with a clear exit.

> Do not claim a specific percentage until the pilot data is attached.`;

export function createMockBackend(options: MockOptions = {}) {
  let stageDelayMs = options.stageDelayMs ?? 120;
  let holdAt: string | null = null;
  let failAt: string | null = null;
  let ttsSeconds = 0.2;
  let releaseHold: (() => void) | null = null;
  const tenants = new Map<string, TenantRecord>();
  const sessions = new Map<string, SessionRecord>();
  const memory = new Map<string, Map<string, string>>();
  const sockets = new Set<WebSocket>();

  function send(ws: WebSocket, event: Json) {
    if (ws.readyState === ws.OPEN) ws.send(JSON.stringify(event));
  }

  const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

  function reply(res: ServerResponse, status: number, body: unknown) {
    res.writeHead(status, { "content-type": "application/json" });
    res.end(JSON.stringify(body));
  }

  function readBody(req: IncomingMessage): Promise<Buffer> {
    return new Promise((resolve, reject) => {
      const chunks: Buffer[] = [];
      req.on("data", (c: Buffer) => chunks.push(c));
      req.on("end", () => resolve(Buffer.concat(chunks)));
      req.on("error", reject);
    });
  }

  async function readJson(req: IncomingMessage): Promise<Json | null> {
    try {
      return JSON.parse((await readBody(req)).toString("utf8")) as Json;
    } catch {
      return null;
    }
  }

  function toWire(s: SessionRecord): Json {
    return {
      id: s.id, tenant_id: s.tenant_id, account_slug: s.account_slug, rep_slug: s.rep_slug, phase: s.phase,
      turns: s.turns, board: s.board, memory_snapshot: s.memory_snapshot, stages: s.stages, artifacts: s.artifacts,
      assets: s.assets, memory_diff: s.memory_diff, strategy_answer: s.strategy_answer,
    };
  }

  function snapshotFor(tenantId: string): Record<string, string> {
    return Object.fromEntries(memory.get(tenantId) ?? []);
  }

  async function speak(ws: WebSocket, sentences: string[]) {
    for (const [index, text] of sentences.entries()) {
      send(ws, { type: "memoria_delta", text: (index === 0 ? "" : " ") + text });
      send(ws, { type: "memoria_sentence", index, text });
      await sleep(15);
    }
    send(ws, { type: "memoria_turn_done", text: sentences.join(" ") });
  }

  async function runBuild(ws: WebSocket, session: SessionRecord) {
    session.phase = "building";
    session.stages = STAGES.map((stage_id) => ({ stage_id, status: "pending", detail: null, duration_ms: null }));
    for (const [i, stage_id] of STAGES.entries()) {
      const running = { stage_id, status: "running", detail: null, duration_ms: null };
      session.stages[i] = running;
      send(ws, { type: "stage", stage: running });
      if (holdAt === stage_id) await new Promise<void>((resolve) => (releaseHold = resolve));
      await sleep(stageDelayMs);

      if (failAt === stage_id) {
        const failed = { stage_id, status: "failed", detail: "Verifier could not reach the model", duration_ms: 400 };
        session.stages[i] = failed;
        session.phase = "failed";
        send(ws, { type: "stage", stage: failed });
        send(ws, { type: "error", message: `The ${stage_id} stage failed`, recoverable: false });
        return;
      }

      if (stage_id === "verifier") {
        for (const asset of assetFixtures(session.id)) {
          session.assets.push(asset);
          send(ws, { type: "asset_ready", asset });
          await sleep(20);
        }
      }
      if (stage_id === "memory_writer") {
        const store = memory.get(session.tenant_id) ?? new Map<string, string>();
        memory.set(session.tenant_id, store);
        const path = `/accounts/${session.account_slug}/objections.md`;
        const before = store.get(path) ?? null;
        const after = `${before ? `${before.trimEnd()}\n` : `# ${session.account_slug} objections\n\n`}- Pricing was raised on ${session.rep_slug}'s call (session ${session.id.slice(0, 8)}).\n`;
        store.set(path, after);
        session.memory_diff = [{ path, change: before === null ? "added" : "modified", before, after }];
        send(ws, { type: "memory_diff", changes: session.memory_diff });
      }
      if (stage_id === "strategy_answer") {
        session.strategy_answer = STRATEGY_ANSWER;
        send(ws, { type: "strategy_answer", text: STRATEGY_ANSWER });
      }

      const done = { stage_id, status: "done", detail: null, duration_ms: STAGE_DURATIONS_MS[i] };
      session.stages[i] = done;
      send(ws, { type: "stage", stage: done });
    }
    session.phase = "complete";
    send(ws, { type: "build_complete" });
  }

  function onSocket(ws: WebSocket, session: SessionRecord) {
    sockets.add(ws);
    ws.on("close", () => sockets.delete(ws));

    if (!session.openingSent) {
      session.openingSent = true;
      const opening = ["Hi, I'm Memoria, your sales engineer.", QUESTIONS[0]];
      session.turns.push({ speaker: "memoria", text: opening.join(" ") });
      void speak(ws, opening);
    }

    ws.on("message", (raw) => {
      let message: Json;
      try {
        message = JSON.parse(String(raw)) as Json;
      } catch {
        send(ws, { type: "error", message: "Message is not valid JSON", recoverable: true });
        return;
      }
      if (message.type === "rep_utterance") {
        const text = typeof message.text === "string" ? message.text.trim() : "";
        if (!text || text.length > 4000 || session.complete) {
          send(ws, { type: "error", message: "Utterance is empty, too long, or the interview is over", recoverable: true });
          return;
        }
        session.turns.push({ speaker: "rep", text });
        const slot = SLOT_ORDER[session.answers];
        session.answers += 1;
        const filled: Slot = { value: text, status: "confirmed", evidence_quote: text, conflicts_with: null, needs_spelling_check: false };
        session.board.slots[slot] = filled;
        send(ws, { type: "slots_changed", updates: [{ slot, ...filled }], board: session.board });

        const finished = session.answers >= ANSWERS_BEFORE_COMPLETE;
        const reply = finished ? ["Thank you, that is everything I need."] : ["Got it.", QUESTIONS[session.answers]];
        session.turns.push({ speaker: "memoria", text: reply.join(" ") });
        void speak(ws, reply).then(() => {
          if (finished) {
            session.complete = true;
            send(ws, { type: "interview_complete", reason: "slots_filled" });
          }
        });
      } else if (message.type === "end_interview") {
        if (!session.complete) {
          session.complete = true;
          send(ws, { type: "interview_complete", reason: "rep_ended" });
        }
      } else if (message.type === "start_build") {
        if (!session.complete || session.building) {
          send(ws, { type: "error", message: "start_build is only valid once, after interview_complete", recoverable: true });
          return;
        }
        session.building = true;
        void runBuild(ws, session);
      } else {
        send(ws, { type: "error", message: `Unknown message type ${String(message.type)}`, recoverable: true });
      }
    });
  }

  async function handle(req: IncomingMessage, res: ServerResponse) {
    const url = new URL(req.url ?? "/", "http://mock");
    const path = url.pathname;
    const method = req.method ?? "GET";

    if (path === "/__mock/reset" && method === "POST") {
      tenants.clear();
      sessions.clear();
      memory.clear();
      stageDelayMs = options.stageDelayMs ?? 120;
      holdAt = null;
      failAt = null;
      ttsSeconds = 0.2;
      releaseHold?.();
      releaseHold = null;
      return reply(res, 200, { ok: true });
    }
    if (path === "/__mock/config" && method === "POST") {
      const body = (await readJson(req)) ?? {};
      if (typeof body.stage_delay_ms === "number") stageDelayMs = body.stage_delay_ms;
      if ("hold_at" in body) holdAt = typeof body.hold_at === "string" ? body.hold_at : null;
      if ("fail_at" in body) failAt = typeof body.fail_at === "string" ? body.fail_at : null;
      if (typeof body.tts_seconds === "number") ttsSeconds = body.tts_seconds;
      return reply(res, 200, { ok: true });
    }
    if (path === "/__mock/release" && method === "POST") {
      holdAt = null;
      releaseHold?.();
      releaseHold = null;
      return reply(res, 200, { ok: true });
    }

    if (path === "/api/health") return reply(res, 200, { status: "ok", mode: "fake" });

    if (path === "/api/tenants" && method === "GET") return reply(res, 200, [...tenants.values()]);

    if (path === "/api/tenants" && method === "POST") {
      const body = await readJson(req);
      const name = typeof body?.name === "string" ? body.name.trim() : "";
      const summary = typeof body?.offering_summary === "string" ? body.offering_summary.trim() : "";
      if (!body || !name || !summary) {
        return reply(res, 422, { detail: [{ loc: ["body", "name"], msg: "String should have at least 1 character", type: "string_too_short" }] });
      }
      const tenant: TenantRecord = {
        id: randomUUID(),
        profile: { brand_voice: "", approved_claims: [], forbidden_claims: [], default_assets: ["deck", "email_sequence"], ...body, name, offering_summary: summary },
        memory_store_id: null,
        documents: [],
      };
      tenants.set(tenant.id, tenant);
      return reply(res, 201, tenant);
    }

    const tenantMatch = path.match(/^\/api\/tenants\/([^/]+)(\/documents)?$/);
    if (tenantMatch) {
      const tenant = tenants.get(decodeURIComponent(tenantMatch[1]));
      if (!tenant) return reply(res, 404, { detail: "Tenant not found" });
      if (!tenantMatch[2] && method === "GET") return reply(res, 200, tenant);
      if (tenantMatch[2] && method === "POST") {
        const body = await readBody(req);
        if (body.length > MAX_UPLOAD_BYTES) return reply(res, 413, { detail: "File is larger than 20 MB" });
        const text = body.toString("latin1");
        const filename = text.match(/name="file"; filename="([^"]*)"/)?.[1] ?? "";
        const scope = text.match(/name="scope"\r\n\r\n([^\r]*)/)?.[1] ?? "tenant";
        const account = text.match(/name="account_slug"\r\n\r\n([^\r]*)/)?.[1] ?? null;
        if (!ALLOWED_UPLOADS.some((ext) => filename.toLowerCase().endsWith(ext))) {
          return reply(res, 415, { detail: "Only PDF, DOCX, MD and TXT files are accepted" });
        }
        const doc = {
          id: randomUUID(),
          filename,
          media_type: filename.endsWith(".md") ? "text/markdown" : "text/plain",
          size_bytes: Math.max(1, body.length - 200),
          scope,
          account_slug: scope === "account" ? account : null,
        };
        tenant.documents.push(doc);
        return reply(res, 201, doc);
      }
    }

    if (path === "/api/sessions" && method === "POST") {
      const body = await readJson(req);
      const tenant = typeof body?.tenant_id === "string" ? tenants.get(body.tenant_id) : undefined;
      for (const field of ["account_slug", "rep_slug"] as const) {
        const value = body?.[field];
        if (typeof value !== "string" || !SLUG.test(value)) {
          return reply(res, 422, { detail: [{ loc: ["body", field], msg: "String should match pattern '^[a-z0-9][a-z0-9-]{0,62}$'", type: "string_pattern_mismatch" }] });
        }
      }
      if (!tenant || !body) return reply(res, 404, { detail: "Tenant not found" });
      const session: SessionRecord = {
        id: randomUUID(),
        tenant_id: tenant.id,
        account_slug: body.account_slug as string,
        rep_slug: body.rep_slug as string,
        phase: "interview",
        turns: [],
        board: emptyBoard(),
        memory_snapshot: snapshotFor(tenant.id),
        stages: [],
        artifacts: {},
        assets: [],
        memory_diff: [],
        strategy_answer: null,
        answers: 0,
        complete: false,
        building: false,
        openingSent: false,
      };
      sessions.set(session.id, session);
      return reply(res, 201, toWire(session));
    }

    const sessionMatch = path.match(/^\/api\/sessions\/([^/]+)(\/assets)?$/);
    if (sessionMatch && method === "GET") {
      const session = sessions.get(decodeURIComponent(sessionMatch[1]));
      if (!session) return reply(res, 404, { detail: "Session not found" });
      return reply(res, 200, sessionMatch[2] ? session.assets : toWire(session));
    }

    const fileMatch = path.match(/^\/api\/files\/([^/]+)\/([^/]+)$/);
    if (fileMatch && method === "GET") {
      const session = sessions.get(decodeURIComponent(fileMatch[1]));
      const name = decodeURIComponent(fileMatch[2]);
      const known = session?.assets.some((a) => (a.files as { url: string }[]).some((f) => f.url.endsWith(`/${name}`)));
      if (!known) return reply(res, 404, { detail: "File not found" });
      res.writeHead(200, { "content-type": CONTENT_TYPES[name.split(".").pop() ?? ""] ?? "application/octet-stream" });
      return res.end(`Mock rendering of ${name}\n`);
    }

    if (path === "/api/tts" && method === "POST") {
      const body = await readJson(req);
      const text = typeof body?.text === "string" ? body.text : "";
      if (!text.trim() || text.length > 600) return reply(res, 400, { detail: "Text must be 1 to 600 characters" });
      res.writeHead(200, { "content-type": "audio/wav" });
      return res.end(silentWav(ttsSeconds));
    }

    return reply(res, 404, { detail: "Not Found" });
  }

  const wss = new WebSocketServer({ noServer: true });
  const server: Server = createServer((req, res) => {
    handle(req, res).catch((error: unknown) => {
      reply(res, 500, { detail: error instanceof Error ? error.message : "Internal error" });
    });
  });

  server.on("upgrade", (req, socket, head) => {
    const match = new URL(req.url ?? "/", "http://mock").pathname.match(/^\/api\/sessions\/([^/]+)\/ws$/);
    const session = match ? sessions.get(decodeURIComponent(match[1])) : undefined;
    if (!session) {
      socket.write("HTTP/1.1 404 Not Found\r\n\r\n");
      socket.destroy();
      return;
    }
    wss.handleUpgrade(req, socket, head, (ws) => onSocket(ws, session));
  });

  return {
    server,
    listen: (port: number) => new Promise<void>((resolve) => server.listen(port, "127.0.0.1", resolve)),
    close: () =>
      new Promise<void>((resolve) => {
        for (const ws of sockets) ws.terminate();
        server.close(() => resolve());
      }),
  };
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  const port = Number(process.env.MOCK_PORT ?? 8765);
  const backend = createMockBackend();
  backend.listen(port).then(() => console.log(`mock backend listening on ${port}`));
}
