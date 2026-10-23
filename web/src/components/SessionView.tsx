"use client";

import Link from "next/link";
import { useSession } from "@/lib/session/use-session";
import { useSpeechInput } from "@/lib/stt/use-speech-input";
import { Build } from "./Build";
import { Interview } from "./Interview";
import { SlotBoard } from "./SlotBoard";
import styles from "./Session.module.css";

const CONNECTION_LABEL = { connecting: "Connecting", open: "Connected", closed: "Disconnected" } as const;
const PHASE_LABEL = { interview: "Interview", building: "Building", complete: "Complete", failed: "Failed" } as const;

export function SessionView({ sessionId }: { sessionId: string }) {
  const session = useSession(sessionId);
  const { state } = session;
  const speech = useSpeechInput({ onTranscript: session.sendUtterance, onBargeIn: session.stopSpeaking });
  const showBuild = state.phase !== "interview";

  if (session.loadError) {
    return (
      <main className={styles.page}>
        <p className="notice notice-danger" role="alert">
          This session could not be loaded: {session.loadError}
        </p>
        <p className={styles.fallbackLink}>
          <Link href="/">Back to tenants</Link>
        </p>
      </main>
    );
  }

  return (
    <main className={styles.page}>
      <header className={styles.topbar}>
        <div className={styles.title}>
          <h1>Session</h1>
          <Link className={styles.back} href="/">
            All tenants
          </Link>
        </div>
        <p className={styles.state}>
          <span className={`badge ${state.connection === "open" ? "badge-ok" : "badge-quiet"}`}>{CONNECTION_LABEL[state.connection]}</span>
          <span className="badge badge-quiet" data-testid="phase">
            {PHASE_LABEL[state.phase]}
          </span>
        </p>
      </header>

      <div className={styles.grid}>
        <div className={styles.column}>
          <Interview
            state={state}
            speech={speech}
            speaking={session.speaking}
            muted={session.muted}
            audioError={session.audioError}
            onMutedChange={session.setMuted}
            onSend={session.sendUtterance}
            onBuild={session.requestBuild}
          />
        </div>
        <div className={styles.column}>
          {showBuild && <Build state={state} />}
          <SlotBoard board={state.board} recentlyChanged={state.recentlyChanged} />
        </div>
      </div>
    </main>
  );
}
