"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { WHISPER_SAMPLE_RATE } from "../audio/resample";
import { MicRecorder, MicrophoneError, hasWebGpu } from "./recorder";
import { Transcriber } from "./transcriber";

export type SpeechStatus =
  | "checking"
  | "unsupported"
  | "needs-download"
  | "downloading"
  | "ready"
  | "starting"
  | "recording"
  | "transcribing";

const MIN_SPEECH_SECONDS = 0.3;

// Whisper emits bracketed or parenthesised markers such as [BLANK_AUDIO] for silence.
const NON_SPEECH_MARKER = /^\s*[[(].*[\])]\s*$/;

interface Options {
  onTranscript: (text: string) => void;
  /** Called the moment the rep starts talking so Memoria's audio can stop. */
  onBargeIn: () => void;
}

export function useSpeechInput({ onTranscript, onBargeIn }: Options) {
  const webGpu = useSyncExternalStore(
    () => () => {},
    hasWebGpu,
    () => null,
  );
  const [override, setStatus] = useState<SpeechStatus | null>(null);
  const status: SpeechStatus = override ?? (webGpu === null ? "checking" : webGpu ? "needs-download" : "unsupported");
  const [downloadFraction, setDownloadFraction] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const transcriberRef = useRef<Transcriber | null>(null);
  const recorderRef = useRef<MicRecorder | null>(null);
  const holdingRef = useRef(false);
  const callbacks = useRef({ onTranscript, onBargeIn });

  useEffect(() => {
    callbacks.current = { onTranscript, onBargeIn };
  });

  const download = useCallback(async () => {
    transcriberRef.current ??= new Transcriber(
      () => new Worker(new URL("./whisper.worker.ts", import.meta.url), { type: "module" }),
    );
    setNotice(null);
    setStatus("downloading");
    try {
      await transcriberRef.current.load(setDownloadFraction);
      setStatus("ready");
    } catch (error) {
      setNotice(`Speech model failed to load: ${error instanceof Error ? error.message : String(error)}`);
      setStatus("needs-download");
    }
  }, []);

  const startTalking = useCallback(async () => {
    if (status !== "ready" || holdingRef.current) return;
    holdingRef.current = true;
    callbacks.current.onBargeIn();
    setNotice(null);
    setStatus("starting");
    recorderRef.current ??= new MicRecorder();
    try {
      await recorderRef.current.start();
    } catch (error) {
      holdingRef.current = false;
      setStatus("ready");
      setNotice(error instanceof MicrophoneError ? error.message : "The microphone could not start.");
      return;
    }
    if (!holdingRef.current) {
      await recorderRef.current.stop();
      setStatus("ready");
      return;
    }
    setStatus("recording");
  }, [status]);

  const stopTalking = useCallback(async () => {
    if (!holdingRef.current) return;
    holdingRef.current = false;
    const recorder = recorderRef.current;
    if (!recorder?.recording) return;
    setStatus("transcribing");
    try {
      const audio = await recorder.stop();
      if (audio.length < MIN_SPEECH_SECONDS * WHISPER_SAMPLE_RATE) {
        setNotice("That was too short. Hold the button a little longer while you speak.");
        return;
      }
      const text = await (transcriberRef.current as Transcriber).transcribe(audio);
      if (!text || NON_SPEECH_MARKER.test(text)) {
        setNotice("No speech was heard. Try again, or type instead.");
        return;
      }
      callbacks.current.onTranscript(text);
    } catch (error) {
      setNotice(`Transcription failed: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setStatus("ready");
    }
  }, []);

  const toggleTalking = useCallback(() => {
    if (holdingRef.current) void stopTalking();
    else void startTalking();
  }, [startTalking, stopTalking]);

  return { status, downloadFraction, notice, download, startTalking, stopTalking, toggleTalking };
}
