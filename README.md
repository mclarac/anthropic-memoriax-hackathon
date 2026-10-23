# Memoria

A voice-first sales engineer agent that works for any company and any product. It keeps per-tenant memory across sessions. See [PLAN.md](PLAN.md) for scope and phases and [docs/architecture.md](docs/architecture.md) for the design.

The stack:

- **`backend/`**: FastAPI API and the Claude chain (Python 3.12+)
- **`web/`**: Next.js voice UI (Node 22+)
- **`tts/`**: Kokoro-82M text-to-speech service, run in a container
- **`datasets/`**: three fictional tenants for tuning and evaluation (see [datasets/README.md](datasets/README.md))

## Prerequisites

- Python 3.12 or newer
- Node.js 22 or newer, with npm
- [Podman](https://podman.io) with `podman compose`. On macOS, run `podman machine start` if the machine is stopped.
- An Anthropic API key, needed only for live mode

## Configure

Create `.env` in the repo root:

```bash
ANTHROPIC_API_KEY=sk-ant-...
```

Don't add quotes or spaces around the `=`. Don't commit this file. It holds a secret.

Fake mode doesn't need a key. Live mode makes real API calls that cost money.

## Install

Backend:

```bash
cd backend
python3.12 -m venv .venv   # any Python 3.12+ works
.venv/bin/pip install -e ".[dev]"
cd ..
```

Frontend:

```bash
cd web
npm ci
cd ..
```

## Run

### Local development

```bash
scripts/dev.sh live    # or: scripts/dev.sh fake
```

This starts three services:

| Service | URL |
|---|---|
| Kokoro TTS (Podman container) | http://localhost:8880 |
| API | http://localhost:8000 |
| Web UI | http://localhost:3000 |

Open http://localhost:3000. Press Ctrl-C to stop everything. `fake` mode replays canned fixtures from `backend/src/memoria/fakes/`. `live` mode reads `ANTHROPIC_API_KEY` from `.env`.

### All containers

```bash
podman compose up --build
```

This builds and runs `tts`, `api` and `web`, and reads `.env`. It runs in live mode by default. Set `MEMORIA_MODE=fake` in the environment to change that.

The Podman VM defaults to 2 GiB of memory, which may be too little for the builds. To raise it:

```bash
podman machine set --memory 4096
```

## Command line

The backend has a `memoria` command:

```bash
cd backend
.venv/bin/memoria serve                                  # API on 0.0.0.0:8000
.venv/bin/memoria card-d --dataset ../datasets/tenant-a --round 1
```

`card-d` runs one dataset round and writes the Card D report to `outputs/` by default. Run it for `--round 1` before `--round 2`, since round 2 builds on round 1's memory.

To run the evaluation harness:

```bash
cd backend
.venv/bin/python -m memoria.eval --out results/run1.json
```

Use `--trials` and `--concurrency` to change the run size. Don't tune prompts against `tenant-c`. It is the holdout set.

## Tests

```bash
# Backend (live API tests are skipped by default)
cd backend && .venv/bin/pytest

# Backend lint
cd backend && .venv/bin/ruff check .

# Web
cd web
npm test              # unit tests (vitest)
npm run typecheck
npm run lint
npm run test:e2e      # Playwright, against a mock backend
```

The end-to-end tests need the Playwright browsers. Install them once with `cd web && npx playwright install chromium`.

## Troubleshooting

- **`ANTHROPIC_API_KEY is required when MEMORIA_MODE=live`**: `.env` is missing, or the key is empty. Check the file is in the repo root.
- **`.venv/bin/uvicorn: No such file or directory`**: run the backend install step above.
- **Python version errors during `pip install`**: the `python3` on your PATH is older than 3.12. Use a newer interpreter, such as `python3.12` or `python3.14`, when creating the venv.
- **A 404 or permission error on the first live request**: the key lacks access to the model in use (`claude-sonnet-5-5`, see `backend/src/memoria/chain_prompts.py`).
- **The TTS container is slow to become healthy**: the model loads on startup. Wait about 30 seconds, then check `curl http://localhost:8880/health`.
