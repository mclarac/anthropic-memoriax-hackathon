# Memoria — API contract

Source of truth for types: `backend/src/memoria/models.py` (Python) and `web/src/lib/contract.ts` (TypeScript mirror). Change both in the same commit.

All endpoints are served by the `api` container on `:8000` under `/api`. The web app calls them through same-origin rewrites (`/api/*` → `api:8000`), so the browser never needs CORS.

## Modes

| Variable | Values | Effect |
|---|---|---|
| `MEMORIA_MODE` | `live` (default), `fake` | `fake` swaps every port (LLM, AgentRuntime, MemoryStore, TTS) for deterministic in-process fakes. Used by pytest and Playwright. |
| `MEMORIA_DATA_DIR` | path, default `./data` | Tenants, sessions, uploaded documents and rendered files. |
| `MEMORIA_TTS_URL` | URL, default `http://tts:8880` | Kokoro service. Ignored in `fake` mode. |
| `ANTHROPIC_API_KEY` | key | Required in `live` mode only. |

## REST

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/health` | | `{"status": "ok", "mode": "live" \| "fake"}` |
| GET | `/api/tenants` | | `Tenant[]` |
| POST | `/api/tenants` | `TenantProfile` | `201 Tenant` |
| GET | `/api/tenants/{tenant_id}` | | `Tenant` or `404` |
| POST | `/api/tenants/{tenant_id}/documents` | multipart: `file`, `scope` (`tenant`\|`account`), `account_slug?` | `201 DocumentRef`. 415 for types other than PDF, DOCX, MD, TXT; 413 over 20 MB |
| POST | `/api/sessions` | `SessionCreate` | `201 Session` (memory snapshot loaded, board empty, phase `interview`) |
| GET | `/api/sessions/{session_id}` | | `Session` |
| GET | `/api/sessions/{session_id}/assets` | | `AssetRef[]` |
| GET | `/api/files/{session_id}/{filename}` | | The rendered file, with the right content type. 404 for anything outside the session's directory. |
| POST | `/api/tts` | `{"text": str, "voice"?: str}` | `audio/wav`. 400 for empty or >600-character text. |

Errors use FastAPI's shape: `{"detail": "..."}`.

## WebSocket `/api/sessions/{session_id}/ws`

One socket per session. Messages are JSON objects with a `type` field.

### Client → server

| type | fields | when |
|---|---|---|
| `rep_utterance` | `text` | The rep finished speaking (Whisper result) or typed a message |
| `end_interview` | | The rep clicks "Build campaign" before the interview ends by itself |
| `start_build` | | Sent after `interview_complete`, to start the backfill lane |

### Server → client

| type | fields | meaning |
|---|---|---|
| `memoria_delta` | `text` | Streamed text of Memoria's current turn |
| `memoria_sentence` | `index`, `text` | A complete sentence; the client requests TTS for it and queues playback in index order |
| `memoria_turn_done` | `text` | The full turn text |
| `slots_changed` | `updates`, `board` | Slot extractor result for the last utterance |
| `interview_complete` | `reason`: `slots_filled` \| `rep_ended` \| `turn_limit` | Interview over; the client shows the build button or auto-starts |
| `stage` | `stage`: `StageState` | Stage progress, sent for every status change |
| `asset_ready` | `asset`: `AssetRef` | A verified, rendered asset |
| `memory_diff` | `changes`: `MemoryChange[]` | Memory store diff for this session |
| `strategy_answer` | `text` | The Card D test-question answer |
| `build_complete` | | All stages finished |
| `error` | `message`, `recoverable` | A stage or turn failed |

### Ordering guarantees

1. On connect the server sends Memoria's opening turn (`memoria_delta`… `memoria_sentence`… `memoria_turn_done`) without waiting for the client.
2. For each `rep_utterance`: the interviewer stream and the slot extraction run concurrently. `slots_changed` may arrive before or after `memoria_turn_done`.
3. Stage events arrive in chain order: `deal_brief, retrieval, research, personas, strategy, assets, verifier, memory_writer, strategy_answer`. `asset_ready` events arrive during `verifier`. `build_complete` is always last.

## Fake mode behavior (for tests)

- The interviewer asks the priority-ordered questions from a fixed script and confirms one priority slot per rep utterance and ends after the 11th utterance (one per priority slot) with `interview_complete{reason: "slots_filled"}`.
- The slot extractor marks the next priority slot `confirmed`, using the utterance as value and quote.
- Each backfill stage returns a fixed, schema-valid fixture from `backend/src/memoria/fakes/fixtures/`.
- MemoryStore keeps snapshots in memory per process. The memory writer adds or modifies `/accounts/{account_slug}/objections.md`, so a second session produces a `modified` diff.
- TTS returns a valid 0.2-second silent WAV.
