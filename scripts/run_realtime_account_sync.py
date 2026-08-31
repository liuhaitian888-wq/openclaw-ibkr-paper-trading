#!/usr/bin/env python3
"""Run realtime account state bus/snapshot/BUY-SELL sync reports."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trading.realtime_account_sync import run_realtime_account_sync


def main() -> int:
    result = run_realtime_account_sync()
    print(
        json.dumps(
            {
                "status": "ok",
                "report": "reports/realtime_account_sync/latest.json",
                "snapshot_id": result["realtime_account_sync"]["snapshot_id"],
                "ibkr_paper_orders_submitted": 0,
                "live_orders_submitted": 0,
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
