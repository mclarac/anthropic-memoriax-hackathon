import {
  parseAssetRef,
  parseMemoryChange,
  parseSlotBoard,
  parseStageState,
  type DocumentRef,
  type Session,
  type SessionCreate,
  type Tenant,
  type TenantProfile,
} from "./contract";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Fetch = (input: string, init?: RequestInit & { headers?: Record<string, string> }) => Promise<Response>;

function describeDetail(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (!Array.isArray(detail)) return null;
  const messages = detail.map((item) => {
    const loc = Array.isArray(item?.loc) ? item.loc.filter((p: unknown) => p !== "body").join(".") : "";
    const msg = typeof item?.msg === "string" ? item.msg : "Invalid value";
    return loc ? `${loc}: ${msg}` : msg;
  });
  return messages.join("; ");
}

async function failure(response: Response): Promise<ApiError> {
  const text = await response.text();
  let message: string | null = null;
  try {
    message = describeDetail((JSON.parse(text) as { detail?: unknown }).detail);
  } catch {
    message = null;
  }
  return new ApiError(response.status, message ?? (response.statusText || `Request failed with ${response.status}`));
}

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) throw await failure(response);
  return (await response.json()) as T;
}

function normalizeSession(raw: Session): Session {
  return {
    ...raw,
    board: parseSlotBoard(raw.board),
    stages: (raw.stages ?? []).map(parseStageState),
    assets: (raw.assets ?? []).map(parseAssetRef),
    memory_diff: (raw.memory_diff ?? []).map(parseMemoryChange),
    turns: raw.turns ?? [],
    strategy_answer: raw.strategy_answer ?? null,
  };
}

export function createApi(fetchImpl: Fetch = (input, init) => fetch(input, init)) {
  const post = (path: string, body: unknown) =>
    fetchImpl(path, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });

  return {
    async listTenants(): Promise<Tenant[]> {
      return json<Tenant[]>(await fetchImpl("/api/tenants"));
    },

    async createTenant(profile: TenantProfile): Promise<Tenant> {
      return json<Tenant>(await post("/api/tenants", profile));
    },

    async uploadDocument(
      tenantId: string,
      file: File,
      target: { scope: "tenant" } | { scope: "account"; accountSlug: string },
    ): Promise<DocumentRef> {
      const form = new FormData();
      form.set("file", file);
      form.set("scope", target.scope);
      if (target.scope === "account") form.set("account_slug", target.accountSlug);
      return json<DocumentRef>(
        await fetchImpl(`/api/tenants/${encodeURIComponent(tenantId)}/documents`, { method: "POST", body: form }),
      );
    },

    async createSession(body: SessionCreate): Promise<Session> {
      return normalizeSession(await json<Session>(await post("/api/sessions", body)));
    },

    async getSession(sessionId: string): Promise<Session> {
      return normalizeSession(await json<Session>(await fetchImpl(`/api/sessions/${encodeURIComponent(sessionId)}`)));
    },

    async synthesize(text: string, signal?: AbortSignal): Promise<ArrayBuffer> {
      const response = await fetchImpl("/api/tts", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ text }),
        signal,
      });
      if (!response.ok) throw await failure(response);
      return response.arrayBuffer();
    },
  };
}

export type Api = ReturnType<typeof createApi>;

export function sessionSocketUrl(sessionId: string, origin: string): string {
  return `${origin.replace(/\/+$/, "")}/api/sessions/${encodeURIComponent(sessionId)}/ws`;
}
