#!/usr/bin/env python3
"""Build IBKR callback wiring audit reports."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trading.ibkr_callback_wiring_audit import build_ibkr_callback_wiring_audit


def main() -> int:
    report = build_ibkr_callback_wiring_audit()
    print(
        json.dumps(
            {
                "status": "ok",
                "report": "reports/ibkr_callback_wiring/latest.json",
                "bus_ok": report["bus_ok"],
                "quote_execution_ready": report["quote_execution_ready"],
                "ibkr_paper_orders_submitted": 0,
                "live_orders_submitted": 0,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
