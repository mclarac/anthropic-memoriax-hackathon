import type { AssetRef, MemoryChange, StageState } from "@/lib/contract";
import { ASSET_LABELS, FORMAT_LABELS, STAGE_LABELS, formatBytes, formatDuration } from "@/lib/format";
import { diffLines } from "@/lib/line-diff";
import type { SessionState } from "@/lib/session/reducer";
import { Markdown } from "./Markdown";
import panel from "./Session.module.css";
import styles from "./Build.module.css";

const STAGE_BADGE: Record<StageState["status"], string> = {
  pending: "badge badge-quiet",
  running: "badge badge-ok",
  done: "badge badge-ok",
  failed: "badge badge-danger",
  skipped: "badge badge-quiet",
};

function StageTimeline({ stages }: { stages: StageState[] }) {
  const done = stages.filter((s) => s.status === "done" || s.status === "skipped").length;
  return (
    <section aria-labelledby="stages-heading">
      <div className={panel.panelHead}>
        <h2 id="stages-heading">Stages</h2>
        <span className={panel.count}>
          {done} of {stages.length} finished
        </span>
      </div>
      <ol className={styles.stages}>
        {stages.map((stage) => (
          <li key={stage.stage_id} className={styles.stage} data-stage={stage.stage_id} data-status={stage.status}>
            <span className={styles.stageName}>
              {STAGE_LABELS[stage.stage_id]}
              {stage.detail && <span className={styles.stageDetail}>{stage.detail}</span>}
            </span>
            <span className={`${STAGE_BADGE[stage.status]} ${stage.status === "running" ? styles.running : ""}`}>
              {stage.status}
            </span>
            <span className={styles.duration}>{formatDuration(stage.duration_ms)}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

function AssetList({ assets, building }: { assets: AssetRef[]; building: boolean }) {
  return (
    <section aria-labelledby="assets-heading">
      <div className={panel.panelHead}>
        <h2 id="assets-heading">Assets</h2>
        <span className={panel.count}>{assets.length} ready</span>
      </div>
      {assets.length === 0 && (
        <p className="empty">{building ? "Assets appear here as the verifier approves them." : "No assets were produced."}</p>
      )}
      <ul className={styles.assets}>
        {assets.map((asset) => (
          <li key={`${asset.asset_type}:${asset.title}`} className={styles.asset} data-asset={asset.asset_type}>
            <div>
              <span className="eyebrow">{ASSET_LABELS[asset.asset_type]}</span>
              <p className={styles.assetTitle}>{asset.title}</p>
            </div>
            <span className={asset.verdict === "pass" ? "badge badge-ok" : "badge badge-warn"}>
              {asset.verdict === "pass" ? "Verified" : "Needs human review"}
            </span>
            <p className={styles.assetMeta}>
              {asset.placeholders.length === 0
                ? "No placeholders"
                : `${asset.placeholders.length} ${asset.placeholders.length === 1 ? "placeholder" : "placeholders"} to fill`}
            </p>
            {asset.placeholders.length > 0 && (
              <ul className={styles.placeholderList} aria-label="Placeholders">
                {asset.placeholders.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            )}
            <div className={styles.downloads}>
              {asset.files.map((file) => (
                <a key={file.url} href={file.url} download>
                  Download {FORMAT_LABELS[file.format]} ({file.format}, {formatBytes(file.size_bytes)})
                </a>
              ))}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function StrategyAnswer({ text, building }: { text: string | null; building: boolean }) {
  return (
    <section aria-labelledby="strategy-heading">
      <div className={panel.panelHead}>
        <h2 id="strategy-heading">Strategy answer</h2>
      </div>
      {text ? <Markdown>{text}</Markdown> : <p className="empty">{building ? "Written in the last stage of the build." : "No answer was produced."}</p>}
    </section>
  );
}

const CHANGE_BADGE: Record<MemoryChange["change"], string> = {
  added: "badge badge-ok",
  modified: "badge badge-warn",
  removed: "badge badge-danger",
};

const MARK = { same: " ", add: "+", remove: "-" } as const;

function MemoryDiff({ changes, building }: { changes: MemoryChange[] | null; building: boolean }) {
  return (
    <section aria-labelledby="memory-heading">
      <div className={panel.panelHead}>
        <h2 id="memory-heading">What Memoria will remember</h2>
        <span className={panel.count}>{changes ? `${changes.length} ${changes.length === 1 ? "file" : "files"} changed` : ""}</span>
      </div>
      {changes === null && <p className="empty">{building ? "The memory diff appears after the memory writer finishes." : "Memory was not changed."}</p>}
      {changes?.length === 0 && <p className="empty">Nothing new was worth remembering.</p>}
      <ul className={styles.changes}>
        {changes?.map((change) => (
          <li key={change.path}>
            <details className={styles.change} data-change={change.change}>
              <summary>
                <span className={CHANGE_BADGE[change.change]}>{change.change}</span>
                <span className={styles.path}>{change.path}</span>
              </summary>
              <div className={styles.diff} role="group" aria-label={`Changes to ${change.path}`}>
                {diffLines(change.before, change.after).map((line, i) => (
                  <div key={i} className={`${styles.line} ${line.kind === "add" ? styles.add : line.kind === "remove" ? styles.remove : ""}`}>
                    <span aria-hidden="true">{MARK[line.kind]}</span>
                    <span>
                      <span className="visually-hidden">{line.kind === "add" ? "Added: " : line.kind === "remove" ? "Removed: " : ""}</span>
                      {line.text || " "}
                    </span>
                  </div>
                ))}
              </div>
            </details>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function Build({ state }: { state: SessionState }) {
  const building = state.phase === "building";
  return (
    <div className={styles.stack}>
      {state.phase === "failed" && (
        <p className={`notice notice-danger ${styles.failedNote}`} role="alert">
          The build stopped{state.error ? `: ${state.error.message}` : "."} Anything produced before the failure is shown below.
        </p>
      )}
      <StageTimeline stages={state.stages} />
      <AssetList assets={state.assets} building={building} />
      <StrategyAnswer text={state.strategyAnswer} building={building} />
      <MemoryDiff changes={state.memoryDiff} building={building} />
    </div>
  );
}
