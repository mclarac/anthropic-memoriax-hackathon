"use client";

import { useEffect, useState } from "react";
import { createApi } from "@/lib/api";
import type { Tenant } from "@/lib/contract";
import { TenantCard } from "./TenantCard";
import { TenantForm } from "./TenantForm";
import styles from "./Home.module.css";

const api = createApi();

type Load = { kind: "loading" } | { kind: "error"; message: string } | { kind: "ready"; tenants: Tenant[] };

export function Home() {
  const [load, setLoad] = useState<Load>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    api
      .listTenants()
      .then((tenants) => !cancelled && setLoad({ kind: "ready", tenants }))
      .catch((e: unknown) => !cancelled && setLoad({ kind: "error", message: e instanceof Error ? e.message : "Could not load tenants" }));
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className={styles.page}>
      <header className={styles.masthead}>
        <h1 className={styles.wordmark}>Memoria</h1>
        <p className={styles.tagline}>
          A sales engineer you talk to. It interviews the rep, gathers the evidence, and builds a verified campaign that
          gets sharper with every account.
        </p>
      </header>

      <div className={styles.columns}>
        <section className={styles.section} aria-labelledby="tenants-heading">
          <h2 id="tenants-heading">Tenants</h2>
          <p className={styles.sectionLead}>
            Each tenant is a seller company with its own memory. Start an interview for an account, or add documents first.
          </p>
          {load.kind === "loading" && <p className="empty" role="status">Loading tenants...</p>}
          {load.kind === "error" && (
            <p className="notice notice-danger" role="alert">
              Could not reach the Memoria API: {load.message}
            </p>
          )}
          {load.kind === "ready" && load.tenants.length === 0 && (
            <p className="empty">No tenants yet. Create the first one to begin.</p>
          )}
          {load.kind === "ready" && load.tenants.length > 0 && (
            <ul className={styles.tenantList}>
              {load.tenants.map((tenant) => (
                <TenantCard key={tenant.id} tenant={tenant} />
              ))}
            </ul>
          )}
        </section>

        <section className={styles.section} aria-labelledby="new-tenant-heading">
          <h2 id="new-tenant-heading">New tenant</h2>
          <p className={styles.sectionLead}>The profile Memoria starts from, before any documents.</p>
          <TenantForm
            onCreated={(tenant) =>
              setLoad((current) => ({ kind: "ready", tenants: [...(current.kind === "ready" ? current.tenants : []), tenant] }))
            }
          />
        </section>
      </div>
    </main>
  );
}
