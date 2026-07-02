#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

unset TRADE_SESSION_TOKEN
unset TRADE_SESSION_TOKEN_FILE

export TRADING_API_HOST=192.168.64.1
export TRADING_API_PORT=8787
export TRADING_MODE=PAPER
export ALLOW_TWS_STAGING=true
export ALLOW_PAPER_TRANSMIT=false
export ALLOW_OUTSIDE_RTH=false
export TRADING_KILL_SWITCH=true
export MAX_ORDER_VALUE=200
export MAX_QUANTITY=1
export MAX_RISK_PER_ORDER=10

echo "Starting Mac Python API in DEV_LOCK."
echo "Trading kill switch: true"
echo "Paper transmit: false"
echo "Trade session token: unset"
echo

exec .venv313/bin/python api_service.py
