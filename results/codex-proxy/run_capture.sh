#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROXY_DIR="$ROOT_DIR/codex-proxy"
LOG_PATH="${LOG_PATH:-$ROOT_DIR/targets/codex/proxy-requests.jsonl}"
BODIES_DIR="${BODIES_DIR:-$ROOT_DIR/targets/codex/proxy-bodies}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-18456}"
UPSTREAM="${UPSTREAM:-https://api.openai.com/v1}"
PROMPT="${*:-Say hello in one sentence.}"

if [[ ! -f "$ROOT_DIR/.env" ]]; then
  echo "missing $ROOT_DIR/.env" >&2
  exit 1
fi

# The project convention is to source .env before invoking the target harness.
set -a
source "$ROOT_DIR/.env"
set +a

mkdir -p "$(dirname "$LOG_PATH")" "$BODIES_DIR"
rm -f "$LOG_PATH"

if ! command -v codex >/dev/null 2>&1; then
  echo "codex is not on PATH" >&2
  exit 1
fi

if ! command -v perl >/dev/null 2>&1; then
  echo "perl is required for the timeout wrapper on macOS" >&2
  exit 1
fi

PROXY_PID=""

cleanup() {
  if [[ -n "$PROXY_PID" ]] && kill -0 "$PROXY_PID" 2>/dev/null; then
    kill "$PROXY_PID" 2>/dev/null || true
    wait "$PROXY_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

cd "$PROXY_DIR"
python3 server.py \
  --host "$HOST" \
  --port "$PORT" \
  --upstream "$UPSTREAM" \
  --log "$LOG_PATH" \
  --bodies-dir "$BODIES_DIR" \
  >"$ROOT_DIR/targets/codex/proxy-server.stdout.log" \
  2>"$ROOT_DIR/targets/codex/proxy-server.stderr.log" &
PROXY_PID=$!

sleep 1

cd "$ROOT_DIR"
perl -e 'alarm shift; exec @ARGV' 60 \
  codex exec \
  --skip-git-repo-check \
  --sandbox read-only \
  --json \
  --output-last-message \
  -c "openai_base_url=\"http://$HOST:$PORT/v1\"" \
  "$PROMPT"
