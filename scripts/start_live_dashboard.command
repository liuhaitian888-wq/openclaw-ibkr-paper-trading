#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")/.."

.venv313/bin/python scripts/serve_live_dashboard.py \
  --symbols AAPL,MSFT,NVDA,TSLA,AMD,INTC,NFLX \
  --refresh-seconds 10 \
  --ibkr-market-data-type 3 \
  --ibkr-exchange SMART \
  --ibkr-timeout 12
