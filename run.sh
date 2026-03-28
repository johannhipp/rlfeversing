#!/usr/bin/env bash
set -euo pipefail

# Orchestrator: reads targets.txt and spawns one Codex worker per target.
# Usage: ./run.sh [--dry-run]

ROOT="$(cd "$(dirname "$0")" && pwd)"
TARGETS_FILE="${ROOT}/targets.txt"
MAX_CONCURRENT=10
DRY_RUN=false
PIDS=()

[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

if [[ ! -f "$TARGETS_FILE" ]]; then
  echo "ERROR: targets.txt not found" >&2
  exit 1
fi

cleanup() {
  echo ""
  echo "Shutting down all workers..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null
  echo "All workers stopped."
}
trap cleanup INT TERM

count=0
while IFS= read -r target || [[ -n "$target" ]]; do
  # Skip empty lines and comments
  target=$(echo "$target" | xargs)
  [[ -z "$target" || "$target" == \#* ]] && continue

  if (( count >= MAX_CONCURRENT )); then
    echo "WARN: max $MAX_CONCURRENT targets reached, skipping: $target"
    continue
  fi

  if [[ -f "${ROOT}/targets/${target}/LOCK" ]]; then
    echo "SKIP: $target (LOCK file exists — already running?)"
    continue
  fi

  if $DRY_RUN; then
    echo "DRY-RUN: would launch worker for '$target'"
  else
    echo "LAUNCH: $target"
    "$ROOT/launch.sh" "$target" &
    PIDS+=($!)
  fi

  (( count++ ))
done < "$TARGETS_FILE"

echo ""
echo "Launched $count workers."

if ! $DRY_RUN && (( ${#PIDS[@]} > 0 )); then
  echo "Press Ctrl+C to stop all workers."
  wait
fi
