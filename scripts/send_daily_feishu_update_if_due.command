#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

mkdir -p .runtime logs

LOG_FILE="logs/daily_feishu_scheduler.log"
PYTHON_BIN="${PYTHON_BIN:-/Users/nbhsbgnb/Documents/New project/.venv313/bin/python}"
NOW_ARG="${FEISHU_SCHEDULER_NOW:+--now=$FEISHU_SCHEDULER_NOW}"

log() {
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG_FILE"
}

if ! SCHEDULER_STATUS="$("$PYTHON_BIN" scripts/daily_feishu_scheduler.py due $NOW_ARG)"; then
  log "skip: $SCHEDULER_STATUS"
  exit 0
fi

log "send: starting daily Feishu visual update: $SCHEDULER_STATUS"
if scripts/send_daily_feishu_update.command >> "$LOG_FILE" 2>&1; then
  "$PYTHON_BIN" scripts/daily_feishu_scheduler.py mark-sent $NOW_ARG >> "$LOG_FILE"
  log "send: completed daily Feishu visual update"
else
  log "send: daily Feishu visual update failed; not marking sent"
  exit 1
fi
