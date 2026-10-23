import { SLOT_GROUPS, type SlotBoard as Board, type SlotStatus } from "@/lib/contract";
import { slotStatusLabel } from "@/lib/format";
import { filledSlotCount } from "@/lib/session/reducer";
import panel from "./Session.module.css";
import styles from "./SlotBoard.module.css";

const BADGE: Record<SlotStatus, string> = {
  open: "badge badge-quiet",
  confirmed: "badge badge-ok",
  rep_unsure: "badge badge-warn",
  conflict: "badge badge-danger",
};

export function SlotBoard({ board, recentlyChanged }: { board: Board; recentlyChanged: string[] }) {
  const total = SLOT_GROUPS.reduce((n, g) => n + g.slots.length, 0);
  return (
    <section aria-labelledby="slots-heading">
      <div className={panel.panelHead}>
        <h2 id="slots-heading">Slot board</h2>
        <span className={panel.count} aria-live="polite">
          {filledSlotCount(board)} of {total} answered
        </span>
      </div>
      <div className={styles.groups}>
        {SLOT_GROUPS.map((group) => (
          <div key={group.label} className={styles.group}>
            <h3 className="eyebrow">{group.label}</h3>
            <ul>
              {group.slots.map((name) => {
                const slot = board.slots[name];
                const hasDetail = Boolean(slot.evidence_quote || slot.conflicts_with || slot.needs_spelling_check);
                return (
                  <li key={name}>
                    <details className={`${styles.slot} ${recentlyChanged.includes(name) ? styles.changed : ""}`} data-slot={name}>
                      <summary>
                        <span className={styles.name}>{name}</span>
                        <span className={BADGE[slot.status]}>{slotStatusLabel(slot.status)}</span>
                        <span className={`${styles.value} ${slot.value ? "" : styles.empty}`}>
                          {slot.value ?? (slot.status === "rep_unsure" ? "Rep is not sure" : "Not discussed yet")}
                        </span>
                      </summary>
                      <div className={styles.detail}>
                        {slot.evidence_quote && (
                          <blockquote className={styles.quote}>
                            <span className="visually-hidden">Evidence: </span>
                            {slot.evidence_quote}
                          </blockquote>
                        )}
                        {slot.conflicts_with && <p>Conflicts with the earlier answer: {slot.conflicts_with}</p>}
                        {slot.needs_spelling_check && <p>Heard by speech recognition. Check the spelling of this name.</p>}
                        {!hasDetail && <p className="muted">No evidence recorded for this slot yet.</p>}
                      </div>
                    </details>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}
