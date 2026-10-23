"use client";

import { useState, type FormEvent } from "react";
import { createApi } from "@/lib/api";
import { ASSET_TYPES, type AssetType, type Tenant } from "@/lib/contract";
import { ASSET_LABELS, linesToList } from "@/lib/format";
import styles from "./Home.module.css";

const api = createApi();

export function TenantForm({ onCreated }: { onCreated: (tenant: Tenant) => void }) {
  const [assets, setAssets] = useState<AssetType[]>(["deck", "email_sequence"]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggle(asset: AssetType, checked: boolean) {
    setAssets((current) => (checked ? [...current, asset] : current.filter((a) => a !== asset)));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy(true);
    setError(null);
    try {
      const tenant = await api.createTenant({
        name: String(data.get("name")).trim(),
        offering_summary: String(data.get("offering_summary")).trim(),
        brand_voice: String(data.get("brand_voice")).trim(),
        approved_claims: linesToList(String(data.get("approved_claims"))),
        forbidden_claims: linesToList(String(data.get("forbidden_claims"))),
        default_assets: ASSET_TYPES.filter((a) => assets.includes(a)),
      });
      form.reset();
      setAssets(["deck", "email_sequence"]);
      onCreated(tenant);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create the tenant");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className={styles.form} onSubmit={submit} aria-label="New tenant">
      <div className="field">
        <label htmlFor="tenant-name">Company name</label>
        <input id="tenant-name" name="name" type="text" required autoComplete="organization" />
      </div>
      <div className="field">
        <label htmlFor="tenant-offering">What you sell</label>
        <textarea id="tenant-offering" name="offering_summary" rows={3} required />
        <span className="hint">One paragraph. Memoria never assumes an industry.</span>
      </div>
      <div className="field">
        <label htmlFor="tenant-voice">Brand voice</label>
        <textarea id="tenant-voice" name="brand_voice" rows={2} />
      </div>
      <div className="field">
        <label htmlFor="tenant-approved">Approved claims</label>
        <textarea id="tenant-approved" name="approved_claims" rows={3} />
        <span className="hint">One per line.</span>
      </div>
      <div className="field">
        <label htmlFor="tenant-forbidden">Forbidden claims</label>
        <textarea id="tenant-forbidden" name="forbidden_claims" rows={3} />
        <span className="hint">One per line.</span>
      </div>
      <fieldset className={styles.fieldset}>
        <legend>Default assets</legend>
        <div className={styles.checks}>
          {ASSET_TYPES.map((asset) => (
            <label key={asset} className={styles.check}>
              <input
                type="checkbox"
                name="default_assets"
                value={asset}
                checked={assets.includes(asset)}
                onChange={(e) => toggle(asset, e.target.checked)}
              />
              {ASSET_LABELS[asset]}
            </label>
          ))}
        </div>
      </fieldset>
      {error && (
        <p className="notice notice-danger" role="alert">
          {error}
        </p>
      )}
      <div>
        <button className="btn btn-primary" type="submit" disabled={busy}>
          {busy ? "Creating..." : "Create tenant"}
        </button>
      </div>
    </form>
  );
}
