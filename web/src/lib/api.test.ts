import { describe, expect, it, vi } from "vitest";
import { ApiError, createApi, sessionSocketUrl } from "./api";
import { SLOT_NAMES, type TenantProfile } from "./contract";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

const profile: TenantProfile = {
  name: "Northwind",
  offering_summary: "Freight software",
  brand_voice: "Plain",
  approved_claims: ["Cuts dwell time"],
  forbidden_claims: [],
  default_assets: ["deck"],
};

describe("api", () => {
  it("POSTs a tenant profile as JSON", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: "t1", profile, memory_store_id: null, documents: [] }, 201));
    const api = createApi(fetchMock);
    const tenant = await api.createTenant(profile);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/tenants");
    expect(init.method).toBe("POST");
    expect(init.headers["content-type"]).toBe("application/json");
    expect(JSON.parse(init.body)).toEqual(profile);
    expect(tenant.id).toBe("t1");
  });

  it("uploads a document as multipart with scope and account slug", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ id: "d1", filename: "a.md", media_type: "text/markdown", size_bytes: 3, scope: "account", account_slug: "acme" }, 201),
    );
    const api = createApi(fetchMock);
    const file = new File(["abc"], "a.md", { type: "text/markdown" });
    await api.uploadDocument("t1", file, { scope: "account", accountSlug: "acme" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/tenants/t1/documents");
    const form = init.body as FormData;
    expect((form.get("file") as File).name).toBe("a.md");
    expect(form.get("scope")).toBe("account");
    expect(form.get("account_slug")).toBe("acme");
    expect(init.headers).toBeUndefined();
  });

  it("omits account_slug for tenant-scoped uploads", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: "d", filename: "a", media_type: "text/plain", size_bytes: 1, scope: "tenant", account_slug: null }, 201));
    await createApi(fetchMock).uploadDocument("t1", new File(["a"], "a.txt"), { scope: "tenant" });
    expect((fetchMock.mock.calls[0][1].body as FormData).has("account_slug")).toBe(false);
  });

  it("raises ApiError carrying FastAPI's detail", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: "Unsupported file type" }, 415));
    await expect(createApi(fetchMock).uploadDocument("t1", new File(["a"], "a.exe"), { scope: "tenant" })).rejects.toMatchObject({
      name: "ApiError",
      status: 415,
      message: "Unsupported file type",
    });
  });

  it("flattens FastAPI validation errors into one readable message", async () => {
    const detail = [{ loc: ["body", "account_slug"], msg: "String should match pattern", type: "string_pattern_mismatch" }];
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail }, 422));
    const error = await createApi(fetchMock).createSession({ tenant_id: "t", account_slug: "x", rep_slug: "y" }).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.message).toBe("account_slug: String should match pattern");
  });

  it("falls back to the status text when the error body is not JSON", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("upstream down", { status: 502, statusText: "Bad Gateway" }));
    await expect(createApi(fetchMock).listTenants()).rejects.toMatchObject({ status: 502, message: "Bad Gateway" });
  });

  it("normalizes a fetched session so the board always has all 16 slots", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        id: "s1", tenant_id: "t1", account_slug: "acme", rep_slug: "sam", phase: "interview",
        turns: [], board: { slots: { pain: { status: "confirmed", value: "slow" } } },
        memory_snapshot: {}, stages: [], assets: [], memory_diff: [], strategy_answer: null,
      }),
    );
    const session = await createApi(fetchMock).getSession("s1");
    expect(Object.keys(session.board.slots)).toEqual(expect.arrayContaining([...SLOT_NAMES]));
    expect(session.board.slots.pain.value).toBe("slow");
    expect(session.board.slots.metrics.status).toBe("open");
  });

  it("requests TTS audio for a sentence and returns the bytes", async () => {
    const bytes = new Uint8Array([82, 73, 70, 70]);
    const fetchMock = vi.fn().mockResolvedValue(new Response(bytes, { status: 200, headers: { "content-type": "audio/wav" } }));
    const audio = await createApi(fetchMock).synthesize("Hello there.");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/tts");
    expect(JSON.parse(init.body)).toEqual({ text: "Hello there." });
    expect(new Uint8Array(audio)).toEqual(bytes);
  });

  it("passes an abort signal through to TTS", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(new Uint8Array(4)));
    const controller = new AbortController();
    await createApi(fetchMock).synthesize("Hi.", controller.signal);
    expect(fetchMock.mock.calls[0][1].signal).toBe(controller.signal);
  });
});

describe("sessionSocketUrl", () => {
  it("joins the origin and session path", () => {
    expect(sessionSocketUrl("abc", "ws://localhost:9000")).toBe("ws://localhost:9000/api/sessions/abc/ws");
  });

  it("tolerates a trailing slash on the origin", () => {
    expect(sessionSocketUrl("abc", "wss://x.example/")).toBe("wss://x.example/api/sessions/abc/ws");
  });

  it("encodes the session id", () => {
    expect(sessionSocketUrl("a/b", "ws://h")).toBe("ws://h/api/sessions/a%2Fb/ws");
  });
});
