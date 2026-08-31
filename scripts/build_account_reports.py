#!/usr/bin/env python3
"""Build read-only account, position, open-order, and daily summary reports."""

import csv
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.position_guard import build_position_guard_report


REPORT_DIR = PROJECT_ROOT / "reports" / "account"


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    guard = build_position_guard_report()
    pnl = latest_pnl_row()
    open_orders = flatten_open_orders(guard)
    positions = [row for row in guard.get("symbols", []) if float(row.get("position_qty") or 0) != 0]
    daily = daily_summary(open_orders)
    timestamp = datetime.now(timezone.utc).isoformat()

    account = {
        "timestamp": timestamp,
        "source": "account_reports",
        "account": guard.get("account") or pnl.get("account"),
        "currency": pnl.get("currency"),
        "daily_pnl": float_or_none(pnl.get("daily_pnl")),
        "realized_pnl": float_or_none(pnl.get("realized_pnl")),
        "unrealized_pnl": float_or_none(pnl.get("unrealized_pnl")),
        "net_liquidation": float_or_none(pnl.get("net_liquidation")),
        "cash": float_or_none(pnl.get("total_cash_value")),
        "buying_power": float_or_none(pnl.get("buying_power")),
        "pnl_timestamp": pnl.get("timestamp"),
        "position_count": len(positions),
        "open_order_count": len(open_orders),
        "status": guard.get("status"),
        "errors": guard.get("errors", []),
    }
    write_json(REPORT_DIR / "latest.json", account)
    write_json(REPORT_DIR / "positions_latest.json", {"timestamp": timestamp, "positions": positions})
    write_json(REPORT_DIR / "open_orders_latest.json", {"timestamp": timestamp, "open_orders": open_orders})
    write_json(REPORT_DIR / "daily_summary_latest.json", {"timestamp": timestamp, **daily})
    print(json.dumps({"account": account, "daily_summary": daily}, indent=2, sort_keys=True))
    return 0


def latest_pnl_row() -> dict[str, str]:
    path = PROJECT_ROOT / "reports" / "pnl_timeseries.csv"
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return {}
    row = dict(rows[-1])
    row.pop(None, None)
    return row


def flatten_open_orders(guard: dict[str, Any]) -> list[dict[str, Any]]:
    orders = []
    for symbol_row in guard.get("symbols", []):
        symbol = symbol_row.get("symbol")
        for order in symbol_row.get("protective_stop_order_details", []):
            item = dict(order)
            item.setdefault("symbol", symbol)
            orders.append(item)
    return orders


def daily_summary(open_orders: list[dict[str, Any]]) -> dict[str, Any]:
    today = datetime.now(timezone.utc).date()
    requests = audit_requests_for_date(today)
    buy_count = 0
    sell_count = 0
    submitted_notional = 0.0
    for row in requests:
        proposal = row.get("proposal", {})
        side = str(proposal.get("side", "")).upper()
        quantity = float_or_none(proposal.get("quantity")) or 0.0
        price = float_or_none(proposal.get("limit_price")) or float_or_none(proposal.get("stop_price")) or 0.0
        if side == "BUY":
            buy_count += 1
        if side == "SELL":
            sell_count += 1
        submitted_notional += quantity * price
    open_sell_orders = sum(1 for order in open_orders if str(order.get("action", "")).upper() == "SELL")
    open_buy_orders = sum(1 for order in open_orders if str(order.get("action", "")).upper() == "BUY")
    return {
        "date_utc": today.isoformat(),
        "daily_order_count": len(requests),
        "daily_sell_order_count": sell_count,
        "daily_buy_order_count": buy_count,
        "daily_submitted_notional": round(submitted_notional, 4),
        "daily_realized_profit_loss": float_or_none(latest_pnl_row().get("realized_pnl")),
        "open_sell_order_count": open_sell_orders,
        "open_buy_order_count": open_buy_orders,
        "execution_records": [],
        "execution_count": 0,
    }


def audit_requests_for_date(day: object) -> list[dict[str, Any]]:
    db = PROJECT_ROOT / "trading_audit.sqlite3"
    if not db.exists():
        return []
    rows: list[dict[str, Any]] = []
    con = sqlite3.connect(db)
    try:
        con.row_factory = sqlite3.Row
        table_exists = con.execute(
            "select 1 from sqlite_master where type = 'table' and name = 'order_requests'"
        ).fetchone()
        if table_exists is None:
            return []
        for row in con.execute("select * from order_requests order by created_at"):
            created_at = str(row["created_at"])
            try:
                created_date = datetime.fromisoformat(created_at).astimezone(timezone.utc).date()
            except ValueError:
                continue
            if created_date != day:
                continue
            proposal = json.loads(row["proposal_json"])
            rows.append({**dict(row), "proposal": proposal})
    finally:
        con.close()
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def float_or_none(value: object) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
