#!/usr/bin/env python3
"""Refresh position protection test result from read-only TWS open-order output."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.position_protection import ACTIVE_ORDER_STATUSES, write_test_repair_result


RESULT_PATH = PROJECT_ROOT / "reports" / "position_protection" / "test_repair_result.json"
ORDERS_PATH = PROJECT_ROOT / "reports" / "list_tws_orders_latest.json"


def refresh_result(result: dict[str, Any], orders_payload: dict[str, Any]) -> dict[str, Any]:
    order = _find_order(result, orders_payload.get("open_orders", []))
    status_values = list(result.get("status_values") or [])
    state_values = list(result.get("open_order_state_values") or [])
    if order:
        if order.get("status"):
            state_values = [str(order["status"])]
        order_status = order.get("order_status") if isinstance(order.get("order_status"), dict) else {}
        if order_status.get("status"):
            status_values = [str(order_status["status"])]
    active = any(value in ACTIVE_ORDER_STATUSES for value in status_values + state_values)
    outside_requested = bool(result.get("outsideRth_requested", result.get("outside_rth")))
    outside_effective = order.get("outside_rth") if order else result.get("outsideRth_effective")
    order_type = str((order or {}).get("order_type") or result.get("order_type") or "")
    side = str((order or {}).get("action") or result.get("side") or "")
    plain_stop_warning = outside_requested and outside_effective is False and side == "SELL" and order_type == "STP"
    warning_reason = "IBKR/TWS plain STP appears RTH-only" if plain_stop_warning else ""

    checks = dict(result.get("checks") or {})
    checks["active_protective_sell_stp"] = active
    checks["side_sell"] = side == "SELL"
    checks["order_type_stp"] = order_type == "STP"
    checks["tif_gtc"] = str((order or {}).get("tif") or result.get("tif")) == "GTC"
    checks["outside_rth_requested"] = outside_requested
    checks["outside_rth_effective_or_explained"] = outside_effective is True or plain_stop_warning

    refreshed = dict(result)
    refreshed.update(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "position_protection_test_repair_result",
            "status_values": status_values,
            "open_order_state_values": state_values,
            "outsideRth_requested": outside_requested,
            "outsideRth_effective": outside_effective,
            "outsideRth_supported": outside_effective is True,
            "outsideRth_warning": plain_stop_warning,
            "outsideRth_warning_reason": warning_reason,
            "checks": checks,
            "success": all(checks.values()),
            "success_with_warning": all(checks.values()) and plain_stop_warning,
            "warning_reason": "outsideRth ineffective for plain STP" if plain_stop_warning else "",
            "blocks_run": not all(checks.values()),
            "matched_open_order": order,
        }
    )
    return refreshed


def _find_order(result: dict[str, Any], orders: list[Any]) -> dict[str, Any]:
    order_ref = result.get("order_ref")
    symbol = result.get("symbol")
    for order in orders:
        if not isinstance(order, dict):
            continue
        if order_ref and order.get("order_ref") == order_ref:
            return order
    for order in orders:
        if not isinstance(order, dict):
            continue
        if symbol and order.get("symbol") == symbol and order.get("action") == "SELL" and order.get("order_type") == "STP":
            return order
    return {}


def main() -> int:
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    orders_payload = json.loads(ORDERS_PATH.read_text(encoding="utf-8"))
    refreshed = refresh_result(result, orders_payload)
    write_test_repair_result(refreshed)
    print(json.dumps(refreshed, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
