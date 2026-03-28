#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROXY_DIR="$ROOT_DIR/cursor-proxy"
LOG_PATH="${LOG_PATH:-$ROOT_DIR/targets/cursor/proxy-exchanges.jsonl}"
REQUESTS_DIR="${REQUESTS_DIR:-$ROOT_DIR/targets/cursor/proxy-requests}"
RESPONSES_DIR="${RESPONSES_DIR:-$ROOT_DIR/targets/cursor/proxy-responses}"
CLIENT_STDOUT_LOG="${CLIENT_STDOUT_LOG:-$ROOT_DIR/targets/cursor/cursor-agent.stdout.log}"
CLIENT_STDERR_LOG="${CLIENT_STDERR_LOG:-$ROOT_DIR/targets/cursor/cursor-agent.stderr.log}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-18457}"
UPSTREAM="${UPSTREAM:-https://api2.cursor.sh}"
WORKSPACE="${WORKSPACE:-$ROOT_DIR}"
CAPTURE_MODE="${CAPTURE_MODE:-models}"
PROXY_HEALTH_URL="${PROXY_HEALTH_URL:-http://$HOST:$PORT/health}"
PROXY_WAIT_SECONDS="${PROXY_WAIT_SECONDS:-10}"
CURSOR_AGENT_BIN="${CURSOR_AGENT_BIN:-$HOME/.local/bin/cursor-agent}"
RUNTIME_HOME="${RUNTIME_HOME:-$HOME}"
SKIP_BIND_CHECK="${SKIP_BIND_CHECK:-0}"
PROMPT="${*:-Say hello in one sentence.}"

if [[ ! -f "$ROOT_DIR/.env" ]]; then
  echo "missing $ROOT_DIR/.env" >&2
  exit 1
fi

set -a
source "$ROOT_DIR/.env"
set +a

mkdir -p "$(dirname "$LOG_PATH")" "$REQUESTS_DIR" "$RESPONSES_DIR"
rm -f "$LOG_PATH"
: >"$CLIENT_STDOUT_LOG"
: >"$CLIENT_STDERR_LOG"

if [[ ! -x "$CURSOR_AGENT_BIN" ]]; then
  echo "cursor-agent is not installed at $CURSOR_AGENT_BIN" >&2
  exit 1
fi

if ! command -v perl >/dev/null 2>&1; then
  echo "perl is required for the timeout wrapper on macOS" >&2
  exit 1
fi

if [[ "$SKIP_BIND_CHECK" != "1" ]]; then
  python3 - "$HOST" "$PORT" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])

sock = socket.socket()
try:
    sock.bind((host, port))
except OSError as exc:
    sys.stderr.write(f"cursor-proxy cannot bind {host}:{port}: {exc}\n")
    sys.stderr.write(
        "Set SKIP_BIND_CHECK=1 to skip this preflight if another process will provide the listener.\n"
    )
    raise SystemExit(1)
finally:
    sock.close()
PY
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
  --exchanges-log "$LOG_PATH" \
  --requests-dir "$REQUESTS_DIR" \
  --responses-dir "$RESPONSES_DIR" \
  >"$ROOT_DIR/targets/cursor/proxy-server.stdout.log" \
  2>"$ROOT_DIR/targets/cursor/proxy-server.stderr.log" &
PROXY_PID=$!

python3 - "$PROXY_PID" "$PROXY_HEALTH_URL" "$PROXY_WAIT_SECONDS" "$ROOT_DIR/targets/cursor/proxy-server.stderr.log" <<'PY'
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

pid = int(sys.argv[1])
url = sys.argv[2]
deadline = time.time() + float(sys.argv[3])
stderr_path = Path(sys.argv[4])

while time.time() < deadline:
    try:
        with urllib.request.urlopen(url, timeout=1) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        if payload.get("ok"):
            raise SystemExit(0)
    except Exception:
        pass

    try:
        os.kill(pid, 0)
    except OSError:
        proc_alive = False
    else:
        proc_alive = True

    if not proc_alive:
        if stderr_path.exists():
            sys.stderr.write(stderr_path.read_text(errors="ignore"))
        sys.stderr.write("cursor-proxy exited before becoming healthy\n")
        raise SystemExit(1)

    time.sleep(0.2)

if stderr_path.exists():
    sys.stderr.write(stderr_path.read_text(errors="ignore"))
sys.stderr.write(f"cursor-proxy did not become healthy at {url}\n")
raise SystemExit(1)
PY

export CURSOR_API_ENDPOINT="http://$HOST:$PORT"
export CURSOR_API_BASE_URL="http://$HOST:$PORT"
export HOME="$RUNTIME_HOME"

CMD=("$CURSOR_AGENT_BIN")
if [[ -n "${CURSOR_API_KEY:-}" ]]; then
  CMD+=("--api-key" "$CURSOR_API_KEY")
fi

case "$CAPTURE_MODE" in
  models)
    CMD+=("models")
    ;;
  status)
    CMD+=("status")
    ;;
  prompt)
    CMD+=("--workspace" "$WORKSPACE" "-p" "--output-format" "json" "$PROMPT")
    ;;
  *)
    echo "unsupported CAPTURE_MODE: $CAPTURE_MODE" >&2
    echo "expected one of: models, status, prompt" >&2
    exit 1
    ;;
esac

cd "$ROOT_DIR"
set +e
perl -e 'alarm shift; exec @ARGV' 60 "${CMD[@]}" >"$CLIENT_STDOUT_LOG" 2>"$CLIENT_STDERR_LOG"
status=$?
set -e

if [[ -s "$CLIENT_STDOUT_LOG" ]]; then
  cat "$CLIENT_STDOUT_LOG"
fi

if [[ -s "$CLIENT_STDERR_LOG" ]]; then
  cat "$CLIENT_STDERR_LOG" >&2
fi

exit "$status"
