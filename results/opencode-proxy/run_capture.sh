#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROXY_DIR="$ROOT_DIR/opencode-proxy"
TARGET_DIR="$ROOT_DIR/targets/opencode"
TMP_DIR="${TMP_DIR:-$ROOT_DIR/.tmp-opencode-proxy}"
CONFIG_HOME="$TMP_DIR/config"
CONFIG_DIR="$CONFIG_HOME/opencode"
REAL_CONFIG_FILE="${REAL_CONFIG_FILE:-$HOME/.config/opencode/opencode.json}"
LOG_PATH="${LOG_PATH:-$TARGET_DIR/proxy-requests.jsonl}"
BODIES_DIR="${BODIES_DIR:-$TARGET_DIR/proxy-bodies}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-18456}"
UPSTREAM="${UPSTREAM:-https://api.openai.com}"
MODE="${MODE:-forward-or-stub}"
MODEL="${MODEL:-openai/gpt-5.2}"
PROMPT="${*:-Say hello in one sentence.}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-60}"
PROXY_STDOUT_LOG="${PROXY_STDOUT_LOG:-$TARGET_DIR/proxy-server.stdout.log}"
PROXY_STDERR_LOG="${PROXY_STDERR_LOG:-$TARGET_DIR/proxy-server.stderr.log}"
RUN_STDOUT_LOG="${RUN_STDOUT_LOG:-$TARGET_DIR/opencode-run.stdout.log}"
RUN_STDERR_LOG="${RUN_STDERR_LOG:-$TARGET_DIR/opencode-run.stderr.log}"
OPENCODE_BIN_DEFAULT="$HOME/.opencode/bin/opencode"
OPENCODE_BIN="${OPENCODE_BIN:-$OPENCODE_BIN_DEFAULT}"

if [[ ! -f "$ROOT_DIR/.env" ]]; then
  echo "missing $ROOT_DIR/.env" >&2
  exit 1
fi

set -a
source "$ROOT_DIR/.env"
set +a

if [[ ! -x "$OPENCODE_BIN" ]]; then
  echo "opencode binary not found at $OPENCODE_BIN" >&2
  exit 1
fi

if ! command -v perl >/dev/null 2>&1; then
  echo "perl is required for the timeout wrapper on macOS" >&2
  exit 1
fi

mkdir -p "$TARGET_DIR" "$BODIES_DIR" "$CONFIG_DIR" "$TMP_DIR"
rm -f "$LOG_PATH" "$PROXY_STDOUT_LOG" "$PROXY_STDERR_LOG" "$RUN_STDOUT_LOG" "$RUN_STDERR_LOG"

REAL_CONFIG_FILE="$REAL_CONFIG_FILE" \
CONFIG_DIR="$CONFIG_DIR" \
HOST="$HOST" \
PORT="$PORT" \
OPENAI_API_KEY="${OPENAI_API_KEY:-dummy}" \
python3 - <<'PY'
import json
import os
from pathlib import Path

real_config = Path(os.environ["REAL_CONFIG_FILE"])
config_dir = Path(os.environ["CONFIG_DIR"])
config_dir.mkdir(parents=True, exist_ok=True)

if real_config.exists():
    data = json.loads(real_config.read_text())
else:
    data = {}

provider = data.setdefault("provider", {}).setdefault("openai", {})
provider.setdefault("api", "openai")
options = provider.setdefault("options", {})
options["baseURL"] = f"http://{os.environ['HOST']}:{os.environ['PORT']}/v1"
options["apiKey"] = os.environ["OPENAI_API_KEY"]
data["permission"] = "allow"
data.setdefault("$schema", "https://opencode.ai/config.json")

(config_dir / "opencode.json").write_text(json.dumps(data, indent=2) + "\n")
PY

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
  --mode "$MODE" \
  --log "$LOG_PATH" \
  --bodies-dir "$BODIES_DIR" \
  >"$PROXY_STDOUT_LOG" \
  2>"$PROXY_STDERR_LOG" &
PROXY_PID=$!

HEALTH_URL="http://${HOST}:${PORT}/health"
for _ in $(seq 1 50); do
  if ! kill -0 "$PROXY_PID" 2>/dev/null; then
    break
  fi
  if HEALTH_URL="$HEALTH_URL" python3 - <<'PY'
import os
import urllib.request

with urllib.request.urlopen(os.environ["HEALTH_URL"], timeout=0.2) as resp:
    raise SystemExit(0 if resp.status == 200 else 1)
PY
  then
    break
  fi
  sleep 0.1
done

if ! kill -0 "$PROXY_PID" 2>/dev/null; then
  echo "proxy failed to start; stderr follows:" >&2
  if [[ -f "$PROXY_STDERR_LOG" ]]; then
    cat "$PROXY_STDERR_LOG" >&2
  fi
  exit 1
fi

if ! HEALTH_URL="$HEALTH_URL" python3 - <<'PY'
import os
import urllib.request

with urllib.request.urlopen(os.environ["HEALTH_URL"], timeout=1) as resp:
    raise SystemExit(0 if resp.status == 200 else 1)
PY
then
  echo "proxy did not become healthy at $HEALTH_URL" >&2
  if [[ -f "$PROXY_STDERR_LOG" ]]; then
    cat "$PROXY_STDERR_LOG" >&2
  fi
  exit 1
fi

cd "$ROOT_DIR"
XDG_CONFIG_HOME="$CONFIG_HOME" \
perl -e 'alarm shift; exec @ARGV' "$TIMEOUT_SECONDS" \
  "$OPENCODE_BIN" run \
  --print-logs \
  --format json \
  --model "$MODEL" \
  "$PROMPT" \
  >"$RUN_STDOUT_LOG" \
  2>"$RUN_STDERR_LOG"

cat "$RUN_STDOUT_LOG"
