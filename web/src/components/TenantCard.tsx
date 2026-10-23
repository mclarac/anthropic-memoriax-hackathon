"use client";

import { useRouter } from "next/navigation";
import { useId, useState, type FormEvent } from "react";
import { createApi } from "@/lib/api";
import { isValidSlug, type DocumentRef, type Tenant } from "@/lib/contract";
import { ASSET_LABELS, formatBytes } from "@/lib/format";
import styles from "./Home.module.css";

const api = createApi();
const SLUG_HINT = "Lowercase letters, digits, hyphens.";

function SlugField({ id, label, value, onChange, showError }: { id: string; label: string; value: string; onChange: (v: string) => void; showError: boolean }) {
  const invalid = showError && !isValidSlug(value);
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={invalid}
        aria-describedby={`${id}-hint`}
        autoCapitalize="none"
        spellCheck={false}
      />
      <span id={`${id}-hint`} className={invalid ? "field-error" : "hint"}>
        {invalid ? `Not valid. ${SLUG_HINT}` : SLUG_HINT}
      </span>
    </div>
  );
}

function StartSession({ tenant }: { tenant: Tenant }) {
  const router = useRouter();
  const id = useId();
  const [account, setAccount] = useState("");
  const [rep, setRep] = useState("");
  const [attempted, setAttempted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setAttempted(true);
    if (!isValidSlug(account) || !isValidSlug(rep)) return;
    setBusy(true);
    setError(null);
    try {
      const session = await api.createSession({ tenant_id: tenant.id, account_slug: account, rep_slug: rep });
      router.push(`/session/${encodeURIComponent(session.id)}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start the session");
      setBusy(false);
    }
  }

  return (
    <form className={styles.tool} onSubmit={submit} aria-label={`Start a session for ${tenant.profile.name}`} noValidate>
      <h4>Start a session</h4>
      <SlugField id={`${id}-account`} label="Account" value={account} onChange={setAccount} showError={attempted} />
      <SlugField id={`${id}-rep`} label="Rep" value={rep} onChange={setRep} showError={attempted} />
      {error && (
        <p className="notice notice-danger" role="alert">
          {error}
        </p>
      )}
      <div>
        <button className="btn btn-primary" type="submit" disabled={busy}>
          {busy ? "Starting..." : "Start interview"}
        </button>
      </div>
    </form>
  );
}

function UploadDocument({ tenant, onUploaded }: { tenant: Tenant; onUploaded: (doc: DocumentRef) => void }) {
  const id = useId();
  const [scope, setScope] = useState<"tenant" | "account">("tenant");
  const [account, setAccount] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [attempted, setAttempted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    setAttempted(true);
    if (!file) {
      setMessage({ text: "Choose a PDF, DOCX, Markdown or text file first.", ok: false });
      return;
    }
    if (scope === "account" && !isValidSlug(account)) return;
    setBusy(true);
    setMessage(null);
    try {
      const doc = await api.uploadDocument(tenant.id, file, scope === "account" ? { scope, accountSlug: account } : { scope });
      onUploaded(doc);
      setMessage({ text: `Uploaded ${doc.filename}.`, ok: true });
      setFile(null);
      form.reset();
    } catch (e) {
      setMessage({ text: e instanceof Error ? e.message : "Upload failed", ok: false });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className={styles.tool} onSubmit={submit} aria-label={`Upload a document for ${tenant.profile.name}`} noValidate>
      <h4>Upload a document</h4>
      <div className="field">
        <label htmlFor={`${id}-scope`}>Scope</label>
        <select id={`${id}-scope`} value={scope} onChange={(e) => setScope(e.target.value as "tenant" | "account")}>
          <option value="tenant">Whole company</option>
          <option value="account">One account</option>
        </select>
      </div>
      {scope === "account" && (
        <SlugField id={`${id}-doc-account`} label="Account" value={account} onChange={setAccount} showError={attempted} />
      )}
      <div className="field">
        <label htmlFor={`${id}-file`}>File</label>
        <input
          id={`${id}-file`}
          type="file"
          accept=".pdf,.docx,.md,.txt"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <span className="hint">PDF, DOCX, Markdown or text, up to 20 MB.</span>
      </div>
      {message && (
        <p className={message.ok ? "status" : "notice notice-danger"} role={message.ok ? "status" : "alert"}>
          {message.text}
        </p>
      )}
      <div>
        <button className="btn" type="submit" disabled={busy}>
          {busy ? "Uploading..." : "Upload"}
        </button>
      </div>
    </form>
  );
}

export function TenantCard({ tenant: initial }: { tenant: Tenant }) {
  const [tenant, setTenant] = useState(initial);
  const { profile } = tenant;

  return (
    <li>
      <article aria-label={profile.name}>
        <div className={styles.tenantHead}>
          <h3>{profile.name}</h3>
          <p className={styles.summary}>{profile.offering_summary}</p>
          <p className={styles.meta}>
            <span>Default assets: {profile.default_assets.map((a) => ASSET_LABELS[a]).join(", ") || "none"}</span>
            <span>
              {tenant.documents.length} {tenant.documents.length === 1 ? "document" : "documents"}
            </span>
          </p>
          {tenant.documents.length > 0 && (
            <ul className={styles.documents} aria-label="Documents">
              {tenant.documents.map((doc) => (
                <li key={doc.id}>
                  <span>{doc.filename}</span>
                  <span className="muted">
                    {formatBytes(doc.size_bytes)}, {doc.scope === "account" ? `account ${doc.account_slug}` : "company"}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className={styles.tenantTools}>
          <StartSession tenant={tenant} />
          <UploadDocument
            tenant={tenant}
            onUploaded={(doc) => setTenant((t) => ({ ...t, documents: [...t.documents, doc] }))}
          />
        </div>
      </article>
    </li>
  );
}
