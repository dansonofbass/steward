#!/usr/bin/env bash
# Fresh vault for the e2e suite. Never points at real data: the data dir is created here and deleted on exit.
# STEWARD_E2E_VAULT=demo (default) seeds the demo household; =empty seeds only two people, for Set up Steward.
set -euo pipefail
cd "$(dirname "$0")/../.."
PORT="${STEWARD_E2E_PORT:-8441}"
VAULT="${STEWARD_E2E_VAULT:-demo}"
DATA="$(mktemp -d)"
touch "$DATA/.e2e-vault"          # vault_keeper.py touches only a vault with this marker
SNAP="$(mktemp -d)"               # the seeded demo vault, put back before each spec
PID=""
GW_PID=""
WATCH_PID=""
cleanup() {
  for p in "$WATCH_PID" "$PID" "$GW_PID"; do
    if [ -n "$p" ]; then
      kill "$p" 2>/dev/null || true
      wait "$p" 2>/dev/null || true
    fi
  done
  rm -rf "$DATA" "$SNAP"
}
trap cleanup EXIT INT TERM
# Playwright starts this script in its own process group and stops it on a normal exit. When Playwright itself is
# killed (a command timeout sends SIGKILL), nothing stops it, and the servers kept their ports for hours. So stop
# when the Playwright run that started us (STEWARD_E2E_OWNER, set in playwright.config.ts) is gone.
OWNER="${STEWARD_E2E_OWNER:-}"
if [ -n "$OWNER" ]; then
  (
    while kill -0 "$OWNER" 2>/dev/null; do sleep 2; done
    # Nothing to say here: our stderr is a pipe to the dead run, and a write to it would end this subshell (SIGPIPE).
    kill -TERM "$$" 2>/dev/null || true
  ) &
  WATCH_PID=$!
fi
# A taken server port stops the run (uvicorn exits when it cannot bind), but the fake gateway runs in the background,
# so its ports (PORT+100, PORT+101) and the vault keeper's (PORT+102) are checked here. If a server left over from an earlier run holds them,
# this run's tests would talk to that run's gateway. Stop instead.
if [ "$VAULT" != "empty" ]; then
  # A bind test, not a connect: it answers at once whether or not anything listens.
  for p in $((PORT + 100)) $((PORT + 101)) $((PORT + 102)); do
    if ! uv run python -c "import socket, sys; s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(('127.0.0.1', int(sys.argv[1])))" "$p" 2>/dev/null; then
      echo "e2e: port $p (the fake gateway's or the vault keeper's) is already in use, probably by an earlier run; stop it or set STEWARD_E2E_BASE_PORT" >&2
      exit 1
    fi
  done
fi
export STEWARD_DATA_DIR="$DATA" STEWARD_BASE_URL="http://localhost:$PORT" STEWARD_ENV=test
export STEWARD_EXPORT_TMP_DIR="$DATA/export-tmp"
export STEWARD_TIMEZONE=America/Los_Angeles   # the zone the e2e seeds and specs were written for (spec 2026-11-05, section 7)
export STEWARD_HOST=127.0.0.1 STEWARD_PORT="$PORT" STEWARD_SYNC_HOURS=0 STEWARD_SIMPLEFIN_HOSTS=testserver STEWARD_STATEMENT_READER=1
uv run steward init-key
if [ "$VAULT" = "empty" ]; then
  uv run steward migrate
  uv run python web/e2e/seed_empty.py
else
  # The demo household (vault_keeper.SEEDS), copied aside for each spec. A restore on a later household day seeds
  # it again: the seeds date their rows from the day they ran.
  uv run python web/e2e/vault_keeper.py seed "$DATA" "$SNAP"
  # The fake gateway (spec 11.5): the real gateway in front of the fake Anthropic server. Never the real API.
  GW_PORT=$((PORT + 100))
  PYTHONPATH="$PWD" uv run python web/e2e/fake_gateway.py "$GW_PORT" "$DATA/gateway-config" "$DATA/gateway-state" &
  GW_PID=$!
  printf '%s' "$(printf 'e2e0%.0s' $(seq 1 16))" > "$DATA/advisor.token"
  chmod 600 "$DATA/advisor.token"
  export STEWARD_GATEWAY_URL="http://127.0.0.1:$GW_PORT"
  # Remote-reading P72: the demo NAS opens PDFs on the stand-in gateway, as the real NAS (no seccomp) does.
  export STEWARD_STATEMENT_READING=gateway
  # Spec 2026-11-05, section 7: the demo names its gateway, so every spec and shot proves the name flows through.
  export STEWARD_GATEWAY_NAME=Zebra-Box
fi
if [ "$VAULT" = "empty" ]; then
  uv run steward serve &
else
  # Each demo spec starts from the snapshot: vault_keeper.py runs the server and restores it on request.
  uv run python web/e2e/vault_keeper.py serve "$DATA" "$SNAP" "$PORT" "$((PORT + 102))" &
fi
PID=$!
wait "$PID"
