#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEFAULT_SHARED_DIR="$HOME/Documents/openclaw_shared"
if [[ ! -d "$DEFAULT_SHARED_DIR" && -d "/Volumes/openclaw_shared" ]]; then
  DEFAULT_SHARED_DIR="/Volumes/openclaw_shared"
fi
SHARED_DIR="${OPENCLAW_SHARED_DIR:-$DEFAULT_SHARED_DIR}"
TOKEN_FILE="$SHARED_DIR/trade_session_token"

cd "$PROJECT_DIR"

if [[ ! -d "$SHARED_DIR" ]]; then
  echo "Shared folder not mounted at $SHARED_DIR."
  echo "Mount/open the shared folder first, then run this script again."
  exit 1
fi

read -r -s -p "Enter today's TRADE_SESSION_TOKEN: " TRADE_SESSION_TOKEN
echo

if [[ -z "$TRADE_SESSION_TOKEN" ]]; then
  echo "Empty token rejected."
  exit 1
fi

printf '%s\n' "$TRADE_SESSION_TOKEN" > "$TOKEN_FILE"
chmod 600 "$TOKEN_FILE" 2>/dev/null || true

export TRADE_SESSION_TOKEN
unset TRADE_SESSION_TOKEN_FILE

export TRADING_API_HOST=192.168.64.1
export TRADING_API_PORT=8787
export TRADING_MODE=PAPER
export ALLOW_TWS_STAGING=true
export ALLOW_PAPER_TRANSMIT=true
export ALLOW_OUTSIDE_RTH=true
export TRADING_KILL_SWITCH=false
export MAX_ORDER_VALUE=400
export MAX_QUANTITY=1
export MAX_RISK_PER_ORDER=10

echo "Starting Mac Python API in TRADE_LOCK."
echo "Trading kill switch: false"
echo "Paper transmit: true"
echo "Shared token file written: $TOKEN_FILE"
echo

exec .venv313/bin/python api_service.py
