#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

mkdir -p .runtime logs

BEIJING_DATE="$(TZ=Asia/Shanghai date +%Y%m%d)"
BEIJING_HOUR="$(TZ=Asia/Shanghai date +%H)"
MARKER=".runtime/daily_feishu_sent_${BEIJING_DATE}"
LOG_FILE="logs/daily_feishu_scheduler.log"

log() {
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG_FILE"
}

if [[ -f "$MARKER" ]]; then
  log "skip: already sent for Beijing date $BEIJING_DATE"
  exit 0
fi

if (( 10#$BEIJING_HOUR < 8 || 10#$BEIJING_HOUR > 11 )); then
  log "skip: outside Beijing send window, hour=$BEIJING_HOUR"
  exit 0
fi

log "send: starting daily Feishu update for Beijing date $BEIJING_DATE"
scripts/send_daily_feishu_update.command >> "$LOG_FILE" 2>&1
touch "$MARKER"
log "send: completed daily Feishu update for Beijing date $BEIJING_DATE"
