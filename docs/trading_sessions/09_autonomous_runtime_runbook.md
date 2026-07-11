# Autonomous Runtime Runbook

Paper-only example:

```bash
set -a
source config/autonomous_paper.env.example
set +a

env TRADING_MODE=PAPER \
  ALLOW_PAPER_TRANSMIT=true \
  ALLOW_OUTSIDE_RTH=true \
  TRADING_KILL_SWITCH=false \
  TRADE_SESSION_TOKEN_FILE="$HOME/Documents/openclaw_shared/trade_session_token" \
  .venv313/bin/python scripts/run_autonomous_paper_runtime.py \
    --symbols AAPL,MSFT,SPY \
    --cycles 0 \
    --sleep-seconds 30
```

`TRADE_LOCK` plus `TRADING_MODE=PAPER` is the automatic paper trading mode. Test results are written into `reports/autonomous_runtime_status.json` and `reports/autonomous_runtime_events.jsonl`; the same runtime path is the stable long-running path.

Live trading remains disabled.
