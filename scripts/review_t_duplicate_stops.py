#!/usr/bin/env python3
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.config import Settings
from trading.position_guard import build_position_guard_report


REPORT_PATH = PROJECT_ROOT / "reports" / "position_guard" / "t_duplicate_stop_review.json"


def main() -> int:
    report = build_position_guard_report(settings=Settings.load())
    row = next((item for item in report.get("symbols", []) if item.get("symbol") == "T"), None)
    stops = [] if row is None else list(row.get("protective_stop_order_details", []))
    signatures = [
        (
            stop.get("total_quantity"),
            stop.get("aux_price"),
            stop.get("order_ref"),
            stop.get("status"),
        )
        for stop in stops
    ]
    duplicate_exact = [sig for sig, count in Counter(signatures).items() if count > 1]
    position_qty = 0.0 if row is None else float(row.get("position_qty") or 0.0)
    stop_qty = 0.0 if row is None else float(row.get("protective_stop_qty") or 0.0)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": "T",
        "position_qty": position_qty,
        "open_sell_stop_orders": stops,
        "total_protective_stop_quantity": stop_qty,
        "total_stop_exceeds_position": stop_qty > position_qty,
        "exact_duplicate_signatures": duplicate_exact,
        "exact_duplicates_found": bool(duplicate_exact),
        "cancellation_recommended": False,
        "reason": (
            "report_only: cancellation requires manual approval unless exact overcoverage is unambiguous"
            if not (stop_qty > position_qty and duplicate_exact)
            else "exact duplicate and overcoverage detected; manual approval still recommended before cancellation"
        ),
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
