#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# dev.sh — start backend + frontend concurrently and wait for both to be up
# ---------------------------------------------------------------------------
# Usage:
#   ./scripts/dev.sh                # start both
#   ./scripts/dev.sh backend        # backend only
#   ./scripts/dev.sh frontend       # frontend only
#
# Requirements: a built backend venv with `pip install -r requirements.txt`
# already run, and `node_modules` installed in frontend/.
# ---------------------------------------------------------------------------

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$REPO_ROOT/backend"
FRONTEND="$REPO_ROOT/frontend"
HEALTH_URL="http://localhost:8000/api/v1/healthz"
FRONT_URL="http://localhost:5173"

log()  { printf "\033[1;36m[dev]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[dev]\033[0m %s\n" "$*" >&2; }
err()  { printf "\033[1;31m[dev]\033[0m %s\n" "$*" >&2; }

cleanup() {
    log "shutting down…"
    if [[ -n "${BACK_PID:-}" ]]; then kill "$BACK_PID" 2>/dev/null || true; fi
    if [[ -n "${FRONT_PID:-}" ]]; then kill "$FRONT_PID" 2>/dev/null || true; fi
    exit 0
}
trap cleanup INT TERM

start_backend() {
    log "starting uvicorn on :8000…"
    ( cd "$BACKEND" \
      && [[ -d .venv ]] && source .venv/bin/activate || true \
      ; exec uvicorn app.main:app --reload --port 8000 ) &
    BACK_PID=$!
}

start_frontend() {
    log "starting vite on :5173…"
    ( cd "$FRONTEND" \
      && exec npm run dev ) &
    FRONT_PID=$!
}

wait_for() {
    local url="$1" name="$2" timeout="${3:-60}"
    local elapsed=0
    log "waiting for $name at $url (up to ${timeout}s)…"
    until curl -fsS "$url" >/dev/null 2>&1; do
        sleep 1
        elapsed=$((elapsed + 1))
        if [[ $elapsed -ge $timeout ]]; then
            err "$name did not become ready in ${timeout}s"
            return 1
        fi
    done
    log "$name is up."
}

case "${1:-all}" in
    backend)
        start_backend
        wait_for "$HEALTH_URL" "backend"
        wait
        ;;
    frontend)
        start_frontend
        wait_for "$FRONT_URL" "frontend"
        wait
        ;;
    all|"")
        start_backend
        start_frontend
        wait_for "$HEALTH_URL" "backend"
        wait_for "$FRONT_URL" "frontend"
        log "backend  → $HEALTH_URL"
        log "frontend → $FRONT_URL"
        log "press Ctrl-C to stop."
        wait
        ;;
    *)
        err "unknown target: $1 (use: all | backend | frontend)"
        exit 2
        ;;
esac