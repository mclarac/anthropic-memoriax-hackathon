# Memoria — Plan

A voice-first sales engineer agent that works for any company and any product, built on the Card D track (`../institutional-memory/scenario-cards.md`) and designed to follow `../Basecamp-Exercises/AI_AGENT_DESIGN_CONSTITUTION.md`.

- Architecture: [`docs/architecture.md`](docs/architecture.md)
- Chain prompts, schemas, call settings: [`backend/src/memoria/chain_prompts.py`](backend/src/memoria/chain_prompts.py)

## Track requirements (pass/fail)

| Requirement | How Memoria meets it |
|---|---|
| Managed Agent + memory store at `/mnt/memory/`, persisting across sessions | Memory-writer and briefer agents; one memory store per tenant |
| Round 1: customer stack, earlier objections, current pitch deck | Interview 1 + uploaded documents |
| Round 2: new objection from the latest call + competitive update from product management | Interview 2 + competitive-update document |
| Same test question both sessions: "Tomorrow's call is the final pitch. What's our strategy?" | Stage 10; saved to `outputs/session{1,2}.txt` |
| Session 2 anticipates the new objection, cites the update, changes the pitch order | Strategy stage lists `changes_from_last_strategy`; the answer leads with "Since our last session" |
| At least one stretch goal | S1 memory policy and S5 per-tenant memory (built in); S3 adversarial round and S8 memory diff (demo) |
| 2-minute demo | Session 1 next to session 2, then the memory diff |

## Decisions

| Topic | Decision |
|---|---|
| Speech-to-text | Whisper on WebGPU in the browser (transformers.js); audio stays on the device |
| Text-to-speech | Kokoro-82M on a FastAPI server, in a Podman container |
| Containers | Podman (`podman compose`): `web` (Next.js), `api` (FastAPI), `tts` (Kokoro) |
| Model | `claude-sonnet-5-5` for every stage (verify access first) |
| Assets | Decks, documents, blogs, email sequences, whitepapers. The model writes JSON; `api` renders `.pptx`, `.docx`/`.pdf`, `.md`/`.html`, `.eml` |
| Scope | Works for any company and any product; tenant profile and documents are inputs |

## Phases

0. **Track baseline on the command line.** Synthetic tenant A (round-1 and round-2 transcripts and documents). Run stages 2–10 from scripts and produce `session1.txt` and `session2.txt`. Meets the track requirements early.
1. **Evaluation.** Tenants B and C (C is the holdout), the simulated rep, deterministic checks, and the judge. Record the baseline before tuning.
2. **Full chain.** Retrieval, research, personas, assets, verifier and reviser, plus renderers.
3. **FastAPI service.** WebSocket for turns and stage progress, memory snapshot and diff, Podman compose.
4. **Next.js voice UI.** Whisper WebGPU, Kokoro playback, live campaign panel.
5. **Demo extras.** Memory diff view (S8), adversarial round 3 (S3), memory curator (S2).

## Open items to verify

See section 6 of `docs/architecture.md`: model and web-tool access, voice time to first token, cache minimum, Kokoro CPU throughput.
