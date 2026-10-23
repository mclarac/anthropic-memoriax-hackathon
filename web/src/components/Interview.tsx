"use client";

import { useEffect, useRef, useState, type FormEvent, type PointerEvent } from "react";
import type { InterviewEndReason } from "@/lib/contract";
import type { SessionState } from "@/lib/session/reducer";
import type { SpeechStatus } from "@/lib/stt/use-speech-input";
import panel from "./Session.module.css";
import styles from "./Interview.module.css";

interface Speech {
  status: SpeechStatus;
  downloadFraction: number;
  notice: string | null;
  download: () => void;
  startTalking: () => void;
  stopTalking: () => void;
  toggleTalking: () => void;
}

interface Props {
  state: SessionState;
  speech: Speech;
  speaking: boolean;
  muted: boolean;
  audioError: string | null;
  onMutedChange: (muted: boolean) => void;
  onSend: (text: string) => boolean;
  onBuild: () => void;
}

const END_REASON: Record<InterviewEndReason, string> = {
  slots_filled: "Every slot is answered.",
  rep_ended: "You ended the interview.",
  turn_limit: "The interview reached its turn limit.",
};

const BUILD_NOTE = {
  interview: "",
  building: "The campaign build is running.",
  complete: "The campaign build finished.",
  failed: "The campaign build stopped with an error.",
} as const;

function isTextEntry(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const interactive = target.closest("input, textarea, select, button, a, summary, [contenteditable='true']");
  return interactive !== null && interactive.getAttribute("data-push-to-talk") === null;
}

export function Interview({ state, speech, speaking, muted, audioError, onMutedChange, onSend, onBuild }: Props) {
  const [draft, setDraft] = useState("");
  const logEnd = useRef<HTMLDivElement>(null);
  const touchActive = useRef(false);
  const { startTalking, stopTalking } = speech;
  const canTalk = speech.status === "ready" || speech.status === "starting" || speech.status === "recording";
  const interviewOpen = state.phase === "interview" && state.connection === "open";
  const recording = speech.status === "recording" || speech.status === "starting";

  useEffect(() => {
    logEnd.current?.scrollIntoView({ block: "end" });
  }, [state.turns.length, state.streaming]);

  useEffect(() => {
    if (!canTalk || !interviewOpen) return;
    const down = (event: KeyboardEvent) => {
      if (event.code !== "Space" || event.repeat || isTextEntry(event.target)) return;
      event.preventDefault();
      startTalking();
    };
    const up = (event: KeyboardEvent) => {
      if (event.code !== "Space" || isTextEntry(event.target)) return;
      event.preventDefault();
      stopTalking();
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, [canTalk, interviewOpen, startTalking, stopTalking]);

  function onPointerDown(event: PointerEvent<HTMLButtonElement>) {
    if (event.pointerType === "touch") {
      touchActive.current = true;
      speech.toggleTalking();
      return;
    }
    touchActive.current = false;
    startTalking();
  }

  function onPointerUp() {
    if (!touchActive.current) stopTalking();
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (onSend(draft)) setDraft("");
  }

  const ended = state.interviewEnded !== null;

  return (
    <section aria-labelledby="interview-heading">
      <div className={panel.panelHead}>
        <h2 id="interview-heading">Interview</h2>
        <span className={panel.count}>{state.turns.filter((t) => t.speaker === "rep").length} answers</span>
      </div>

      <div className={styles.transcript} role="log" aria-live="polite" aria-label="Conversation" tabIndex={0}>
        {state.turns.length === 0 && state.streaming === null && (
          <p className="empty">
            {state.connection === "open" ? "Memoria is about to start the interview..." : "Waiting for the connection..."}
          </p>
        )}
        {state.turns.map((turn, i) => (
          <div key={i} data-speaker={turn.speaker} className={`${styles.turn} ${turn.speaker === "memoria" ? styles.memoria : styles.rep}`}>
            <span className={styles.speaker}>{turn.speaker === "memoria" ? "Memoria" : "You"}</span>
            <p className={styles.text}>{turn.text}</p>
          </div>
        ))}
        {state.streaming !== null && (
          <div data-speaker="memoria" data-streaming="" className={`${styles.turn} ${styles.memoria} ${styles.streaming}`}>
            <span className={styles.speaker}>Memoria</span>
            <p className={styles.text}>{state.streaming}</p>
          </div>
        )}
        <div ref={logEnd} />
      </div>

      {state.error && (
        <p className="notice notice-danger" role="alert" style={{ marginTop: 16 }}>
          {state.error.message}
        </p>
      )}

      <div className={styles.controls}>
        <div className={styles.talkRow}>
          {speech.status === "needs-download" && (
            <button type="button" className="btn" onClick={speech.download}>
              Enable voice input
            </button>
          )}
          {speech.status === "downloading" && (
            <label className={styles.hint}>
              Downloading the speech model, first time only ({Math.round(speech.downloadFraction * 100)}%)
              <br />
              <progress className={styles.progress} value={speech.downloadFraction} max={1} />
            </label>
          )}
          {(canTalk || speech.status === "transcribing") && (
            <button
              type="button"
              className={`btn ${styles.talk}`}
              data-push-to-talk=""
              data-active={recording}
              aria-pressed={recording}
              disabled={!interviewOpen || speech.status === "transcribing"}
              onPointerDown={onPointerDown}
              onPointerUp={onPointerUp}
              onPointerLeave={onPointerUp}
              onClick={(event) => event.preventDefault()}
            >
              <span className={styles.dot} aria-hidden="true" />
              {speech.status === "transcribing" ? "Transcribing..." : recording ? "Listening..." : "Hold to talk"}
            </button>
          )}
          <button
            type="button"
            className="btn btn-quiet"
            aria-pressed={muted}
            onClick={() => onMutedChange(!muted)}
          >
            {muted ? "Unmute Memoria" : "Mute Memoria"}
          </button>
          {speaking && (
            <span className={styles.speaking} role="status">
              <span className={styles.bars} aria-hidden="true">
                <span />
                <span />
                <span />
              </span>
              Memoria is speaking
            </span>
          )}
        </div>

        {speech.status === "unsupported" && (
          <p className="notice" role="note">
            Voice input needs WebGPU, which this browser does not offer. Type your answers below instead. Nothing is
            lost: Memoria still speaks its questions aloud.
          </p>
        )}
        {canTalk && (
          <p className={styles.hint}>Hold the button or the Space bar while you speak. On touch screens, tap to start and tap to stop.</p>
        )}
        {speech.notice && (
          <p className="notice" role="status">
            {speech.notice}
          </p>
        )}
        {audioError && (
          <p className="notice" role="status">
            Voice playback is unavailable: {audioError}. The text of every turn is still shown.
          </p>
        )}

        <form className={styles.typeForm} onSubmit={submit}>
          <div className="field">
            <label htmlFor="type-instead">Type instead</label>
            <input
              id="type-instead"
              type="text"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              disabled={!interviewOpen}
              autoComplete="off"
              maxLength={4000}
            />
          </div>
          <button type="submit" className="btn" disabled={!interviewOpen || draft.trim() === ""}>
            Send
          </button>
        </form>

        {state.connection === "closed" && (
          <p className="notice notice-danger" role="alert">
            The connection to Memoria closed. Reload the page to reconnect.
          </p>
        )}

        <div className={styles.buildRow}>
          {state.phase === "interview" && (
            <>
              <button
                type="button"
                className={`btn ${ended ? "btn-primary" : ""}`}
                onClick={onBuild}
                disabled={state.connection !== "open" || state.buildRequested}
              >
                {state.buildRequested ? "Starting build..." : "Build campaign"}
              </button>
              <span className={styles.hint}>
                {ended
                  ? `${END_REASON[state.interviewEnded as InterviewEndReason]} Ready to build.`
                  : "Ends the interview here and builds from what has been answered."}
              </span>
            </>
          )}
          {state.phase !== "interview" && (
            <span className={styles.hint}>
              {ended ? `${END_REASON[state.interviewEnded as InterviewEndReason]} ` : ""}
              {BUILD_NOTE[state.phase]}
            </span>
          )}
        </div>
      </div>
    </section>
  );
}
