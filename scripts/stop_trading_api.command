#!/usr/bin/env bash
set -euo pipefail

DEFAULT_SHARED_DIR="$HOME/Documents/openclaw_shared"
if [[ ! -d "$DEFAULT_SHARED_DIR" && -d "/Volumes/openclaw_shared" ]]; then
  DEFAULT_SHARED_DIR="/Volumes/openclaw_shared"
fi
SHARED_DIR="${OPENCLAW_SHARED_DIR:-$DEFAULT_SHARED_DIR}"
TOKEN_FILE="$SHARED_DIR/trade_session_token"

unset TRADE_SESSION_TOKEN
unset TRADE_SESSION_TOKEN_FILE

if [[ -f "$TOKEN_FILE" ]]; then
  : > "$TOKEN_FILE"
  chmod 600 "$TOKEN_FILE" 2>/dev/null || true
  echo "Cleared shared token file: $TOKEN_FILE"
fi

if pgrep -f "api_service.py" >/dev/null 2>&1; then
  pkill -f "api_service.py" || true
  echo "Stopped running api_service.py process."
else
  echo "No running api_service.py process found."
fi

echo "STOP complete."
