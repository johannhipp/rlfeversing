#!/usr/bin/env bash
set -euo pipefail

# Usage: ./launch.sh <target-name>
# Spawns a single Codex worker for the given target harness.

TARGET="${1:?Usage: ./launch.sh <target-name>}"
ROOT="$(cd "$(dirname "$0")" && pwd)"

# Load env vars (API keys etc.)
if [[ -f "$ROOT/.env" ]]; then
  set -a
  source "$ROOT/.env"
  set +a
fi
WORKDIR="${ROOT}/targets/${TARGET}"

mkdir -p "$WORKDIR"
echo "$$" > "$WORKDIR/LOCK"

cleanup() { rm -f "$WORKDIR/LOCK"; }
trap cleanup EXIT

CYCLE=1
while true; do
  echo "[$(date)] ${TARGET}: starting RALF cycle ${CYCLE}"

  # Re-read prompt each cycle (agents may have updated skill.md, which prompt references)
  PROMPT=$(sed "s/{{TARGET}}/${TARGET}/g" "$ROOT/prompt.md")

  codex exec \
    --full-auto \
    -C "$ROOT" \
    "$PROMPT" || echo "[$(date)] ${TARGET}: cycle ${CYCLE} exited with $?"

  echo "[$(date)] ${TARGET}: cycle ${CYCLE} complete"
  CYCLE=$((CYCLE + 1))
  sleep 5
done
