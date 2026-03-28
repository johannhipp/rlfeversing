#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROXY_DIR="$ROOT_DIR/continue-proxy"
TARGET_DIR="$ROOT_DIR/targets/continue"
LOG_PATH="${LOG_PATH:-$TARGET_DIR/proxy-exchanges.jsonl}"
REQUESTS_DIR="${REQUESTS_DIR:-$TARGET_DIR/proxy-requests}"
RESPONSES_DIR="${RESPONSES_DIR:-$TARGET_DIR/proxy-responses}"
CONFIG_PATH="${CONFIG_PATH:-$TARGET_DIR/proxy-config.yaml}"
CLI_STDOUT_LOG="${CLI_STDOUT_LOG:-$TARGET_DIR/continue.stdout.log}"
CLI_STDERR_LOG="${CLI_STDERR_LOG:-$TARGET_DIR/continue.stderr.log}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-18431}"
UPSTREAM="${UPSTREAM:-https://api.openai.com}"
MODE="${MODE:-forward-or-stub}"
MODEL_NAME="${MODEL_NAME:-gpt-4o-mini}"
PROVIDER_NAME="${PROVIDER_NAME:-openai}"
CONTINUE_CMD="${CONTINUE_CMD:-cn}"
CONTINUE_CMD_ARGS="${CONTINUE_CMD_ARGS:-}"
CONFIG_API_KEY_VALUE="${CONFIG_API_KEY_VALUE:-continue-proxy-dummy}"
PROMPT="${*:-Say hello in one short sentence.}"

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

CMD_WORDS_FILE="$(mktemp "${TMPDIR:-/tmp}/continue-proxy-cmd.XXXXXX")"
python3 - <<'PY' >"$CMD_WORDS_FILE"
import os
import shlex
import sys

for raw in (os.environ.get("CONTINUE_CMD", "cn"), os.environ.get("CONTINUE_CMD_ARGS", "")):
    for item in shlex.split(raw):
        sys.stdout.write(item)
        sys.stdout.write("\n")
PY

set --
while IFS= read -r word || [ -n "$word" ]; do
  set -- "$@" "$word"
done <"$CMD_WORDS_FILE"
rm -f "$CMD_WORDS_FILE"

if [[ "$#" -eq 0 ]]; then
  echo "continue command is empty after parsing CONTINUE_CMD/CONTINUE_CMD_ARGS" >&2
  exit 1
fi

CONTINUE_CMD_BIN="$1"
if ! command -v "$CONTINUE_CMD_BIN" >/dev/null 2>&1 && [[ ! -x "$CONTINUE_CMD_BIN" ]]; then
  echo "continue CLI command not found: $CONTINUE_CMD_BIN" >&2
  echo "set CONTINUE_CMD=/absolute/path/to/cn if it is installed elsewhere" >&2
  echo "or set CONTINUE_CMD='npx -y @continuedev/cli' (and optionally CONTINUE_CMD_ARGS=...)" >&2
  exit 1
fi

UPSTREAM_AUTH_VALUE="${UPSTREAM_AUTH_VALUE:-}"
if [[ -z "$UPSTREAM_AUTH_VALUE" && -n "${CONTINUE_API_KEY:-}" ]]; then
  UPSTREAM_AUTH_VALUE="Bearer ${CONTINUE_API_KEY}"
elif [[ -z "$UPSTREAM_AUTH_VALUE" && -n "${OPENAI_API_KEY:-}" ]]; then
  UPSTREAM_AUTH_VALUE="Bearer ${OPENAI_API_KEY}"
fi
UPSTREAM_AUTH_HEADER="${UPSTREAM_AUTH_HEADER:-Authorization}"
mkdir -p "$TARGET_DIR" "$REQUESTS_DIR" "$RESPONSES_DIR"
rm -f "$LOG_PATH"
find "$REQUESTS_DIR" -maxdepth 1 -type f -delete
find "$RESPONSES_DIR" -maxdepth 1 -type f -delete
rm -f "$CLI_STDOUT_LOG" "$CLI_STDERR_LOG" \
  "$TARGET_DIR/proxy-server.stdout.log" "$TARGET_DIR/proxy-server.stderr.log"

python3 - <<'PY' "$CONFIG_PATH" "$HOST" "$PORT" "$MODEL_NAME" "$PROVIDER_NAME" "$CONFIG_API_KEY_VALUE"
from pathlib import Path
import sys

config_path = Path(sys.argv[1])
host = sys.argv[2]
port = sys.argv[3]
model_name = sys.argv[4]
provider_name = sys.argv[5]
api_key = sys.argv[6]

config_path.write_text(
    "\n".join(
        [
            "models:",
            "  - name: local-proxy",
            f"    provider: {provider_name}",
            f"    model: {model_name}",
            f"    apiKey: {api_key}",
            f"    apiBase: http://{host}:{port}/v1",
            "",
        ]
    ),
    encoding="utf-8",
)
config_path.chmod(0o600)
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
SERVER_ARGS=(
  python3 server.py
  --host "$HOST" \
  --port "$PORT" \
  --upstream "$UPSTREAM" \
  --mode "$MODE" \
  --exchanges-log "$LOG_PATH" \
  --requests-dir "$REQUESTS_DIR" \
  --responses-dir "$RESPONSES_DIR"
)
if [[ -n "$UPSTREAM_AUTH_VALUE" ]]; then
  SERVER_ARGS+=(--upstream-auth-header "$UPSTREAM_AUTH_HEADER" --upstream-auth-value "$UPSTREAM_AUTH_VALUE")
fi
"${SERVER_ARGS[@]}" \
  >"$TARGET_DIR/proxy-server.stdout.log" \
  2>"$TARGET_DIR/proxy-server.stderr.log" &
PROXY_PID=$!

if ! kill -0 "$PROXY_PID" 2>/dev/null; then
  echo "continue-proxy failed to start; see $TARGET_DIR/proxy-server.stderr.log" >&2
  exit 1
fi

python3 - <<'PY' "$HOST" "$PORT" "$PROXY_PID" "$TARGET_DIR/proxy-server.stderr.log"
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

host = sys.argv[1]
port = sys.argv[2]
proxy_pid = int(sys.argv[3])
stderr_log = Path(sys.argv[4])
url = f"http://{host}:{port}/health"
deadline = time.time() + 10
last_error = None

while time.time() < deadline:
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("ok") is True:
            sys.exit(0)
        last_error = f"unexpected health payload: {payload!r}"
    except Exception as exc:
        last_error = str(exc)

    try:
        os.kill(proxy_pid, 0)
    except OSError:
        if stderr_log.exists():
            sys.stderr.write(stderr_log.read_text(encoding="utf-8", errors="replace"))
            if last_error:
                sys.stderr.write("\n")
        sys.stderr.write(
            f"continue-proxy exited before becoming healthy at {url}"
            + (f": {last_error}" if last_error else "")
            + "\n"
        )
        sys.exit(1)

    time.sleep(0.25)

if stderr_log.exists():
    sys.stderr.write(stderr_log.read_text(encoding="utf-8", errors="replace"))
    if last_error:
        sys.stderr.write("\n")

sys.stderr.write(
    f"continue-proxy did not become healthy at {url} within 10 seconds"
    + (f": {last_error}" if last_error else "")
    + "\n"
)
sys.exit(1)
PY

cd "$ROOT_DIR"
perl -e 'alarm shift; exec @ARGV' 60 \
  "$@" \
  --config "$CONFIG_PATH" \
  -p "$PROMPT" \
  >"$CLI_STDOUT_LOG" \
  2>"$CLI_STDERR_LOG"
