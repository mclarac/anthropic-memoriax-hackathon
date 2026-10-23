#!/usr/bin/env bash
# Local development: Kokoro in a podman container, backend with reload, Next.js dev server.
# Usage: scripts/dev.sh [fake|live]   (default: fake; live reads ANTHROPIC_API_KEY from .env)
set -euo pipefail

mode="${1:-fake}"
root="$(cd "$(dirname "$0")/.." && pwd)"
pids=()

case "$mode" in
  fake | live) ;;
  *) echo "mode must be fake or live, got '$mode'" >&2; exit 2 ;;
esac

if [ "$mode" = live ]; then
  [ -f "$root/.env" ] || { echo "live mode needs $root/.env (see .env.example)" >&2; exit 1; }
  set -a; . "$root/.env"; set +a
fi

cleanup() {
  trap - INT TERM EXIT
  if [ ${#pids[@]} -gt 0 ]; then kill "${pids[@]}" 2>/dev/null || true; fi
  podman stop memoria-tts >/dev/null 2>&1 || true
}
trap cleanup INT TERM EXIT

podman image exists memoria-tts || podman build -t memoria-tts "$root/tts"
podman rm -f memoria-tts >/dev/null 2>&1 || true
podman run -d --rm --name memoria-tts -p 8880:8880 memoria-tts >/dev/null

(
  cd "$root/backend"
  MEMORIA_MODE="$mode" MEMORIA_TTS_URL=http://localhost:8880 \
    exec .venv/bin/uvicorn memoria.app:create_app --factory --reload --port 8000
) &
pids+=($!)

(
  cd "$root/web"
  MEMORIA_API_URL=http://localhost:8000 NEXT_PUBLIC_MEMORIA_WS_ORIGIN=ws://localhost:8000 \
    exec npm run dev
) &
pids+=($!)

echo "tts :8880  api :8000 ($mode)  web :3000  (Ctrl-C to stop)"
wait
