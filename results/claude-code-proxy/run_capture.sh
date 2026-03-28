#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROXY_DIR="$ROOT_DIR/claude-code-proxy"
TARGET_DIR="$ROOT_DIR/targets/claude-code"
REQUEST_LOG_PATH="${REQUEST_LOG_PATH:-$TARGET_DIR/proxy-requests.jsonl}"
RESPONSE_LOG_PATH="${RESPONSE_LOG_PATH:-$TARGET_DIR/proxy-responses.jsonl}"
BODIES_DIR="${BODIES_DIR:-$TARGET_DIR/proxy-bodies}"
PROXY_STDOUT_LOG="${PROXY_STDOUT_LOG:-$TARGET_DIR/proxy-server.stdout.log}"
PROXY_STDERR_LOG="${PROXY_STDERR_LOG:-$TARGET_DIR/proxy-server.stderr.log}"
RUN_STDOUT_LOG="${RUN_STDOUT_LOG:-$TARGET_DIR/claude-run.stdout.log}"
RUN_STDERR_LOG="${RUN_STDERR_LOG:-$TARGET_DIR/claude-run.stderr.log}"
DEBUG_FILE="${DEBUG_FILE:-$TARGET_DIR/claude-run.debug.log}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-18441}"
UPSTREAM="${UPSTREAM:-https://api.anthropic.com}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-60}"
ENABLE_TOOL_SEARCH_VALUE="${ENABLE_TOOL_SEARCH_VALUE:-true}"
CLAUDE_BIN="${CLAUDE_BIN:-/opt/homebrew/bin/claude}"
OUTPUT_FORMAT="${OUTPUT_FORMAT:-text}"
CLAUDE_HOME="${CLAUDE_HOME:-}"
PROMPT="${*:-Reply with exactly OK.}"

if [[ ! -f "$ROOT_DIR/.env" ]]; then
  echo "missing $ROOT_DIR/.env" >&2
  exit 1
fi

set -a
source "$ROOT_DIR/.env"
set +a

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required" >&2
  exit 1
fi

if ! command -v perl >/dev/null 2>&1; then
  echo "perl is required for the timeout wrapper on macOS" >&2
  exit 1
fi

if [[ ! -x "$CLAUDE_BIN" ]]; then
  echo "claude binary not found at $CLAUDE_BIN" >&2
  exit 1
fi

mkdir -p "$TARGET_DIR"
rm -f "$REQUEST_LOG_PATH" "$RESPONSE_LOG_PATH" "$PROXY_STDOUT_LOG" "$PROXY_STDERR_LOG" "$RUN_STDOUT_LOG" "$RUN_STDERR_LOG" "$DEBUG_FILE"
rm -rf "$BODIES_DIR"
mkdir -p "$BODIES_DIR"

PROXY_PID=""

cleanup() {
  if [[ -n "$PROXY_PID" ]] && kill -0 "$PROXY_PID" 2>/dev/null; then
    kill "$PROXY_PID" 2>/dev/null || true
    wait "$PROXY_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

wait_for_proxy() {
  local url="http://$HOST:$PORT/health"
  python3 - <<'PY' "$PROXY_PID" "$url" "$PROXY_STDERR_LOG"
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

pid = int(sys.argv[1])
url = sys.argv[2]
stderr_log = Path(sys.argv[3])
deadline = time.time() + 10
last_error = None

while time.time() < deadline:
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("ok") is True:
            raise SystemExit(0)
        last_error = f"unexpected health payload: {payload!r}"
    except Exception as exc:
        last_error = str(exc)

    try:
        os.kill(pid, 0)
    except OSError:
        if stderr_log.exists():
            sys.stderr.write(stderr_log.read_text(encoding="utf-8", errors="replace"))
            if last_error:
                sys.stderr.write("\n")
        sys.stderr.write(
            f"claude-code-proxy exited before becoming healthy at {url}"
            + (f": {last_error}" if last_error else "")
            + "\n"
        )
        raise SystemExit(1)

    time.sleep(0.25)

if stderr_log.exists():
    sys.stderr.write(stderr_log.read_text(encoding="utf-8", errors="replace"))
    if last_error:
        sys.stderr.write("\n")

sys.stderr.write(
    f"claude-code-proxy did not become healthy at {url} within 10 seconds"
    + (f": {last_error}" if last_error else "")
    + "\n"
)
raise SystemExit(1)
PY
}

cd "$PROXY_DIR"
python3 server.py \
  --host "$HOST" \
  --port "$PORT" \
  --upstream "$UPSTREAM" \
  --request-log "$REQUEST_LOG_PATH" \
  --response-log "$RESPONSE_LOG_PATH" \
  --bodies-dir "$BODIES_DIR" \
  >"$PROXY_STDOUT_LOG" \
  2>"$PROXY_STDERR_LOG" &
PROXY_PID=$!

wait_for_proxy

cd "$ROOT_DIR"
if [[ -n "$CLAUDE_HOME" ]]; then
  HOME="$CLAUDE_HOME" \
  ANTHROPIC_BASE_URL="http://$HOST:$PORT" \
  ENABLE_TOOL_SEARCH="$ENABLE_TOOL_SEARCH_VALUE" \
  perl -e 'alarm shift; exec @ARGV' "$TIMEOUT_SECONDS" \
    "$CLAUDE_BIN" \
    -p "$PROMPT" \
    --output-format "$OUTPUT_FORMAT" \
    --verbose \
    --debug-file "$DEBUG_FILE" \
    >"$RUN_STDOUT_LOG" \
    2>"$RUN_STDERR_LOG"
else
  ANTHROPIC_BASE_URL="http://$HOST:$PORT" \
  ENABLE_TOOL_SEARCH="$ENABLE_TOOL_SEARCH_VALUE" \
  perl -e 'alarm shift; exec @ARGV' "$TIMEOUT_SECONDS" \
    "$CLAUDE_BIN" \
    -p "$PROMPT" \
    --output-format "$OUTPUT_FORMAT" \
    --verbose \
    --debug-file "$DEBUG_FILE" \
    >"$RUN_STDOUT_LOG" \
    2>"$RUN_STDERR_LOG"
fi

cat "$RUN_STDOUT_LOG"
