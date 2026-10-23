"use client";

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { createApi, sessionSocketUrl } from "../api";
import { SentencePlaybackQueue } from "../audio/playback-queue";
import { WebAudioPlayer } from "../audio/web-audio-player";
import { parseServerEvent, type ClientMessage } from "../contract";
import { initialSessionState, sessionReducer } from "./reducer";

const WS_ORIGIN = process.env.NEXT_PUBLIC_MEMORIA_WS_ORIGIN ?? "ws://localhost:8000";

export function useSession(sessionId: string) {
  const api = useMemo(() => createApi(), []);
  const [state, dispatch] = useReducer(sessionReducer, undefined, initialSessionState);
  const [speaking, setSpeaking] = useState(false);
  const [muted, setMutedState] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [audioError, setAudioError] = useState<string | null>(null);

  const socketRef = useRef<WebSocket | null>(null);
  const mutedRef = useRef(false);
  const turnRef = useRef(0);
  const turnInProgressRef = useRef(false);
  const playerRef = useRef<WebAudioPlayer | null>(null);
  const queueRef = useRef<SentencePlaybackQueue<AudioBuffer> | null>(null);
  const abortRef = useRef(new Set<AbortController>());

  const ensureQueue = useCallback(() => {
    if (!queueRef.current) {
      playerRef.current = new WebAudioPlayer();
      queueRef.current = new SentencePlaybackQueue(playerRef.current, setSpeaking);
    }
    return { queue: queueRef.current, player: playerRef.current as WebAudioPlayer };
  }, []);

  const stopSpeaking = useCallback(() => {
    for (const controller of abortRef.current) controller.abort();
    abortRef.current.clear();
    const throughTurn = turnInProgressRef.current ? turnRef.current : turnRef.current - 1;
    queueRef.current?.clear(throughTurn);
  }, []);

  const loadClip = useCallback(
    async (text: string): Promise<AudioBuffer | null> => {
      if (mutedRef.current) return null;
      const { player } = ensureQueue();
      const controller = new AbortController();
      abortRef.current.add(controller);
      try {
        const wav = await api.synthesize(text, controller.signal);
        const clip = await player.decode(wav);
        setAudioError(null);
        return clip;
      } catch (error) {
        if (controller.signal.aborted) return null;
        setAudioError(error instanceof Error ? error.message : "Voice playback failed");
        return null;
      } finally {
        abortRef.current.delete(controller);
      }
    },
    [api, ensureQueue],
  );

  useEffect(() => {
    let cancelled = false;
    let socket: WebSocket | null = null;
    const abortControllers = abortRef.current;

    const handleFrame = (frame: string) => {
      const parsed = parseServerEvent(frame);
      if (!parsed.ok) {
        dispatch({ type: "error", message: `Unreadable message from the server: ${parsed.error}`, recoverable: true });
        return;
      }
      const { event } = parsed;
      if (event.type === "memoria_delta") turnInProgressRef.current = true;
      if (event.type === "memoria_sentence") {
        turnInProgressRef.current = true;
        ensureQueue().queue.add(turnRef.current, event.index, loadClip(event.text));
      }
      if (event.type === "memoria_turn_done") {
        queueRef.current?.closeTurn(turnRef.current);
        turnRef.current += 1;
        turnInProgressRef.current = false;
      }
      dispatch(event);
    };

    async function connect() {
      try {
        const session = await api.getSession(sessionId);
        if (cancelled) return;
        turnRef.current = session.turns.filter((t) => t.speaker === "memoria").length;
        dispatch({ type: "hydrate", session });
      } catch (error) {
        if (!cancelled) setLoadError(error instanceof Error ? error.message : "Could not load the session");
        return;
      }
      socket = new WebSocket(sessionSocketUrl(sessionId, WS_ORIGIN));
      socketRef.current = socket;
      socket.onopen = () => dispatch({ type: "connection", status: "open" });
      socket.onclose = () => dispatch({ type: "connection", status: "closed" });
      socket.onmessage = (message) => handleFrame(String(message.data));
    }

    void connect();
    return () => {
      cancelled = true;
      socket?.close();
      socketRef.current = null;
      for (const controller of abortControllers) controller.abort();
      queueRef.current?.clear(turnRef.current);
    };
  }, [sessionId, api, ensureQueue, loadClip]);

  useEffect(() => {
    const unlock = () => void playerRef.current?.unlock();
    window.addEventListener("pointerdown", unlock);
    window.addEventListener("keydown", unlock);
    return () => {
      window.removeEventListener("pointerdown", unlock);
      window.removeEventListener("keydown", unlock);
    };
  }, []);

  const send = useCallback((message: ClientMessage): boolean => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;
    socket.send(JSON.stringify(message));
    return true;
  }, []);

  const sendUtterance = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return false;
      stopSpeaking();
      if (!send({ type: "rep_utterance", text: trimmed })) return false;
      dispatch({ type: "rep_sent", text: trimmed });
      return true;
    },
    [send, stopSpeaking],
  );

  const requestBuild = useCallback(() => {
    if (state.interviewEnded) {
      if (send({ type: "start_build" })) dispatch({ type: "build_started" });
      return;
    }
    if (send({ type: "end_interview" })) dispatch({ type: "build_requested" });
  }, [send, state.interviewEnded]);

  // The server only accepts start_build after interview_complete, so a build the rep
  // asked for early is started here as soon as the interview has ended.
  useEffect(() => {
    if (state.buildRequested && state.interviewEnded) {
      if (send({ type: "start_build" })) dispatch({ type: "build_started" });
    }
  }, [state.buildRequested, state.interviewEnded, send]);

  const setMuted = useCallback(
    (value: boolean) => {
      mutedRef.current = value;
      setMutedState(value);
      if (value) stopSpeaking();
    },
    [stopSpeaking],
  );

  return { state, speaking, muted, setMuted, stopSpeaking, sendUtterance, requestBuild, loadError, audioError };
}
