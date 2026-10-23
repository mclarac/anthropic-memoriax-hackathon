# Memoria — Architecture

Memoria is a voice-first sales engineer agent that works for any company and any product. It interviews a sales rep, retrieves and researches evidence, builds target personas, and produces a campaign: decks, documents, blogs, email sequences and whitepapers. Its memory is per company (tenant), so it gets sharper on each account over time.

Stage prompts, schemas and call settings: [`../backend/src/memoria/chain_prompts.py`](../backend/src/memoria/chain_prompts.py).

## 1. System and deployment

```mermaid
flowchart LR
  subgraph Browser["Browser (rep's laptop)"]
    UI["Next.js UI<br/>interview + live campaign panel"]
    STT["Whisper on WebGPU<br/>(transformers.js)<br/>audio never leaves the device"]
    PLAY["Audio playback"]
    STT -- transcript text --> UI
  end

  subgraph Podman["Podman pod: memoria (podman compose)"]
    WEB["web<br/>Next.js server :3000"]
    API["api<br/>FastAPI :8000<br/>orchestrator · eval runner · renderers"]
    TTS["tts<br/>Kokoro-82M on FastAPI :8880"]
    VOL[("volume: data/<br/>tenants · runs · rendered assets")]
    API --- VOL
  end

  subgraph Anthropic["Anthropic platform"]
    MSG["Messages API<br/>claude-sonnet-5-5<br/>structured outputs · caching"]
    WS["web_search / web_fetch<br/>server tools"]
    FILES["Files API<br/>tenant + account documents"]
    MA["Managed Agents<br/>memoria-memory-writer<br/>memoria-briefer"]
    MEM[("Memory stores<br/>one per tenant<br/>/mnt/memory/")]
    MA --- MEM
  end

  UI <-- "WebSocket: turns, stage progress" --> WEB
  WEB <--> API
  API -- "spoken text, per sentence" --> TTS
  TTS -- "audio stream" --> PLAY
  API <--> MSG
  MSG <--> WS
  API --> FILES
  API <-- "sessions + event stream" --> MA
  API -- "read snapshot (memories.list/retrieve)" --> MEM
```

| Container | Role | Notes |
|---|---|---|
| `web` | Next.js app; serves the UI and Whisper model files | Whisper weights are cached by the browser after first load |
| `api` | FastAPI: runs the chain, keeps session state, renders assets, runs evals | The only container holding the Anthropic key (from `.env`, never baked into the image) |
| `tts` | Kokoro-82M behind a small FastAPI | Runs on CPU under Podman on macOS (no GPU passthrough) |

## 2. The chain

Two lanes (Constitution §7.7). The **interactive** lane is the voice interview: streamed, short, and fast. The **backfill** lane builds the campaign while the UI shows each stage's progress.

```mermaid
flowchart TB
  subgraph L1["Interactive lane: voice interview (repeat per turn, max 25 turns)"]
    direction LR
    REP(["Rep speaks"]) --> W["Whisper WebGPU"] --> U["utterance"]
    U --> I1["1a Interviewer<br/>plain spoken text, streamed"]
    U --> I2["1b Slot extractor<br/>JSON slot updates"]
    I2 --> BOARD[("Slot board<br/>MEDDPICC + campaign slots")]
    BOARD --> I1
    SNAP[("Memory snapshot<br/>read once at start")] --> I1
    I1 --> K["Kokoro TTS"] --> SPK(["Memoria speaks"])
  end

  L1 -- "interview complete" --> B2

  subgraph L2["Backfill lane: campaign build"]
    B2["2 Deal Brief<br/>transcript + board + memory → brief, what_changed"]
    B3["3 Retrieval<br/>uploaded docs → evidence E1..En"]
    B4["4 Deep research<br/>plan ≤8 questions → web_search/fetch (≤20 calls)<br/>→ final structured ledger"]
    B5["5 Personas<br/>buying committee, evidenced or hypothesis"]
    B6["6 Strategy<br/>changes vs last time · objection matrix · battle card<br/>pitch order · outreach · asset plan"]
    B7["7 Asset generators (parallel, one per requested asset)<br/>deck · document · blog · email sequence · whitepaper"]
    B8{"8 Verifier<br/>every claim vs ledger"}
    B8R["8b Reviser<br/>max 1 pass"]
    REN["Renderers in api<br/>.pptx · .docx/.pdf · .md/.html · .eml"]
    B9["9 Memory writer<br/>Managed Agent, read_write"]
    B10["10 Strategy answer<br/>'Tomorrow's call is the final pitch.<br/>What's our strategy?'"]
    LEDGER[("Evidence ledger<br/>E# · quote · source · date")]

    B2 --> B3 --> B4 --> B5 --> B6 --> B7 --> B8
    B8 -- pass --> REN
    B8 -- needs_revision --> B8R --> B8
    B8 -- "fails twice" --> HR["Ship with 'needs human review' banner"]
    REN --> B9 --> B10
    B3 --> LEDGER
    B4 --> LEDGER
    LEDGER -.-> B5 & B6 & B7 & B8
  end
```

| # | Stage | Runtime | Output | Gate / failure behavior |
|---|---|---|---|---|
| 1a | Interviewer | Messages, streamed, effort low, 200 tokens | Spoken turn | One question per turn; refuses to invent statistics |
| 1b | Slot extractor | Messages, structured | Slot updates with verbatim quotes | `conflict` status when the rep contradicts memory |
| 2 | Deal Brief | Messages, structured | Brief + `what_changed` + stable objection IDs | Unknown → null; transcript beats memory |
| 3 | Retrieval | Messages + document blocks (citations) | Ledger entries | Only what documents state; conflicts recorded |
| 4 | Deep research | Messages tool loop, then a structured final call with `tool_choice: none` | Ledger entries + question outcomes | ≤20 tool calls; "unanswerable" is a valid outcome |
| 5 | Personas | Messages, structured | Buying committee | Each statement is evidenced or labelled a hypothesis |
| 6 | Strategy | Messages, structured, effort high | Full campaign strategy | Must list changes from the previous strategy |
| 7 | Assets | Messages, structured, parallel | Content JSON per asset | `[E#]` markers on every fact; placeholders, never invention |
| 8 | Verifier | Messages, structured, effort high | Per-claim verdicts | `pass` only if every claim is supported |
| 9 | Memory writer | Managed Agent + tenant memory store | Updated `/mnt/memory/` | Update, never duplicate; objections never deleted |
| 10 | Strategy answer | Managed Agent, memory read-only | The track's test-question answer | Leads with "Since our last session: ..." |

**Why the model writes JSON and the API renders the files:** asset content comes back as structured output, and deterministic Python renderers (python-pptx, python-docx, markdown → HTML/PDF) build the files. That keeps formatting off the model's output budget (§7.5), makes every claim checkable before rendering, and means files never have to leave an agent container.

## 3. One round, end to end (Card D)

```mermaid
sequenceDiagram
  autonumber
  actor Rep
  participant UI as Next.js + Whisper
  participant API as FastAPI
  participant TTS as Kokoro
  participant LLM as Messages API
  participant AG as Managed Agent
  participant MEM as Tenant memory store

  Rep->>UI: Opens session (tenant, account)
  UI->>API: start(tenant, account, uploaded docs)
  API->>MEM: list + retrieve account files
  MEM-->>API: memory snapshot (empty in session 1)
  loop Each interview turn
    Rep->>UI: speaks
    UI->>API: utterance text
    par
      API->>LLM: 1a Interviewer (stream)
      LLM-->>API: spoken sentences
      API->>TTS: sentence by sentence
      TTS-->>UI: audio
    and
      API->>LLM: 1b Slot extractor
      LLM-->>API: slot updates → board
    end
  end
  API->>LLM: 2–8 brief → retrieval → research → personas → strategy → assets → verify
  API-->>UI: stage progress + rendered assets
  API->>AG: 9 Memory writer session (read_write)
  AG->>MEM: update account files, mark superseded objections
  API->>AG: 10 "Tomorrow's call is the final pitch. What's our strategy?"
  AG->>MEM: read
  AG-->>API: strategy answer
  API-->>UI: answer + memory diff (S8)
  Note over Rep,MEM: Session 2 repeats this with a new objection and a competitive update.<br/>The interview opens from memory, and the answer leads with what changed.
```

## 4. Memory and tenant isolation

```mermaid
flowchart LR
  subgraph TA["Tenant A memory store"]
    A1["README.md (policy version)"]
    A2["accounts/acct-1/<br/>profile · stakeholders · objections<br/>competitors · strategy · open-questions"]
    A3["playbook/what-worked.md"]
    A4["reps/rep-x.md"]
  end
  subgraph TB2["Tenant B memory store"]
    B1["README.md"]
    B2x["accounts/..."]
  end
  SA["Session for tenant A"] -- "attach A only" --> TA
  SB["Session for tenant B"] -- "attach B only" --> TB2
  SA -. "never" .-x TB2
```

- **Isolation (S5):** one memory store per tenant, and a session attaches only its own tenant's store. The eval plants a unique canary string in each tenant's data and fails if it ever appears in another tenant's output.
- **Policy (S1):** the always and never lists live in `MEMORY_WRITER_SYSTEM`. Objections change status (`open → answered | superseded`) with a date and reason; they are never deleted.
- **Contradictions (S3):** an unexplained conflict goes to `open-questions.md` as an "unresolved conflict", and the old value stays in place until the rep confirms.
- **Memory diff (S8):** the API snapshots the store before and after each session and shows the diff in the UI. This is the headline of the demo.

## 5. Evaluation

```mermaid
flowchart LR
  DS[("Datasets<br/>tenant A, tenant B: tuning<br/>tenant C: holdout, never tuned on<br/>each: fact sheet · round1 · round2 · round3 (adversarial)")]
  SIM["Simulated rep<br/>plays the hidden fact sheet<br/>STT-style speech"]
  RUN["Eval runner (FastAPI job)<br/>5 trials per task · bounded parallelism"]
  DET["Deterministic checks<br/>slot recall vs fact sheet · new objection ID present<br/>pitch order changed · objections.md superseded<br/>canary absent · every asset verifier = pass"]
  JUD["LLM judge, one criterion each<br/>PASS/FAIL first line"]
  REP2[("results/*.json<br/>rate · pass@k · pass^k<br/>cost · TTFT · TTC")]
  DS --> SIM --> RUN --> DET & JUD --> REP2
```

Failed runs (API errors, timeouts) are recorded separately from failed tasks. A task passes only if **every** check passes.

## 6. Open items to verify (not yet confirmed)

- That `claude-sonnet-5-5` is enabled for this key, along with the `web_search`/`web_fetch` server tools. Check both with `institutional-memory/test_api_access.py`.
- Voice time to first token for the interviewer at effort low. If it's too slow, drop to Haiku for stage 1a only, and measure before and after.
- Whether `MEMORIA_CORE` plus the stage and tenant blocks reaches the 2,048-token caching minimum on Sonnet. Confirm with `usage.cache_read_input_tokens`.
- Kokoro CPU throughput in Podman on macOS when sentences are synthesized in parallel with streaming.
