#!/usr/bin/env python3
"""Run read-only REAL_IBKR callback bridge dry-run."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trading.ibkr_callback_bridge import run_ibkr_callback_dry_run


def main() -> int:
    duration = float(os.getenv("IBKR_CALLBACK_DRY_RUN_SECONDS", "60"))
    symbols = [item.strip().upper() for item in os.getenv("IBKR_CALLBACK_DRY_RUN_SYMBOLS", "AAPL,MSFT,PFE,T").split(",") if item.strip()]
    report = run_ibkr_callback_dry_run(duration_seconds=duration, symbols=symbols)
    print(
        json.dumps(
            {
                "status": "ok",
                "report": "reports/ibkr_callback_dry_run/latest.json",
                "connected": report["connected"],
                "bus_status": report["bus_status"],
                "orders_submitted": 0,
                "orders_cancelled": 0,
                "snapshot_request_used": False,
                "regulatory_snapshot_used": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
