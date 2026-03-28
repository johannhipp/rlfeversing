#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROXY_DIR="$ROOT_DIR/aider-proxy"
LOG_PATH="${LOG_PATH:-$ROOT_DIR/targets/aider/proxy-traffic.jsonl}"
BODIES_DIR="${BODIES_DIR:-$ROOT_DIR/targets/aider/proxy-bodies}"
PROXY_STDOUT_LOG="${PROXY_STDOUT_LOG:-$ROOT_DIR/targets/aider/proxy-server.stdout.log}"
PROXY_STDERR_LOG="${PROXY_STDERR_LOG:-$ROOT_DIR/targets/aider/proxy-server.stderr.log}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-18457}"
UPSTREAM="${UPSTREAM:-https://api.openai.com/v1}"
MODEL="${MODEL:-openai/gpt-4o-mini}"
AIDER_CMD_PREFIX="${AIDER_CMD_PREFIX:-}"
AIDER_BIN="${AIDER_BIN:-aider}"
AIDER_ARGS="${AIDER_ARGS:-}"
PROMPT="${*:-Say hello in one sentence.}"

if [[ ! -f "$ROOT_DIR/.env" ]]; then
  echo "missing $ROOT_DIR/.env" >&2
  exit 1
fi

set -a
source "$ROOT_DIR/.env"
set +a

mkdir -p "$(dirname "$LOG_PATH")" "$BODIES_DIR"
rm -f "$LOG_PATH"
rm -rf "$BODIES_DIR"
mkdir -p "$BODIES_DIR"
rm -f "$PROXY_STDOUT_LOG" "$PROXY_STDERR_LOG"

if ! command -v perl >/dev/null 2>&1; then
  echo "perl is required for the timeout wrapper on macOS" >&2
  exit 1
fi

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "OPENAI_API_KEY is not set in .env" >&2
  exit 1
fi

declare -a AIDER_CMD
if [[ -n "$AIDER_CMD_PREFIX" ]]; then
  read -r -a AIDER_CMD <<<"$AIDER_CMD_PREFIX"
elif command -v "$AIDER_BIN" >/dev/null 2>&1; then
  AIDER_CMD=("$AIDER_BIN")
elif [[ "$AIDER_BIN" == "aider" ]] && command -v python3 >/dev/null 2>&1 && python3 - <<'PY'
import importlib.util
raise SystemExit(0 if importlib.util.find_spec("aider") else 1)
PY
then
  AIDER_CMD=(python3 -m aider)
else
  echo "$AIDER_BIN is not on PATH and no importable Python aider module was found" >&2
  exit 1
fi

if [[ -n "$AIDER_ARGS" ]]; then
  read -r -a aider_extra <<<"$AIDER_ARGS"
  AIDER_CMD+=("${aider_extra[@]}")
fi

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
  local attempt
  for attempt in $(seq 1 40); do
    if ! kill -0 "$PROXY_PID" 2>/dev/null; then
      echo "proxy exited before becoming ready" >&2
      return 1
    fi

    if python3 - "$url" <<'PY'
import json
import sys
import urllib.request

url = sys.argv[1]
try:
    with urllib.request.urlopen(url, timeout=0.5) as response:
        payload = json.load(response)
    raise SystemExit(0 if payload.get("ok") is True else 1)
except Exception:
    raise SystemExit(1)
PY
    then
      return 0
    fi

    sleep 0.25
  done

  echo "proxy did not become ready at $url" >&2
  return 1
}

cd "$PROXY_DIR"
python3 server.py \
  --host "$HOST" \
  --port "$PORT" \
  --upstream "$UPSTREAM" \
  --log "$LOG_PATH" \
  --bodies-dir "$BODIES_DIR" \
  >"$PROXY_STDOUT_LOG" \
  2>"$PROXY_STDERR_LOG" &
PROXY_PID=$!

wait_for_proxy

cd "$ROOT_DIR"
perl -e 'alarm shift; exec @ARGV' 60 \
  "${AIDER_CMD[@]}" \
  --model "$MODEL" \
  --openai-api-key "$OPENAI_API_KEY" \
  --openai-api-base "http://$HOST:$PORT/v1" \
  --message "$PROMPT"
