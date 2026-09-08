#!/usr/bin/env python3
"""Build read-only account, position, open-order, and daily diagnostic reports."""

import csv
import json
import sqlite3
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.production_paths import AUDIT_DB, REPORT_ROOT

from trading.position_guard import build_position_guard_report
from trading.account_state_manager import build_account_state, account_execution_readiness_payload
from scripts.daily_trading_report_view import render_daily_report_markdown


REPORT_DIR = REPORT_ROOT / "account"
DAILY_REPORT_DIR = REPORT_ROOT / "daily_trading"
NEW_YORK = ZoneInfo("America/New_York")


from trading.production_guard import guarded_service

@guarded_service("reports")
def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    guard = build_position_guard_report()
    pnl = latest_pnl_row()
    open_orders = flatten_open_orders(guard)
    positions = [row for row in guard.get("symbols", []) if float(row.get("position_qty") or 0) != 0]
    daily = daily_summary(open_orders)
    account_state = build_account_state(position_guard_report=guard, account_snapshot=account_from_guard_and_pnl(guard, pnl), write_reports_enabled=True)
    readiness = account_execution_readiness_payload(account_state)
    diagnostic = daily_diagnostic_report(account_state, readiness)
    timestamp = datetime.now(timezone.utc).isoformat()

    account = account_from_guard_and_pnl(guard, pnl)
    account.update({"timestamp": timestamp, "position_count": len(positions), "open_order_count": len(open_orders), "status": guard.get("status"), "errors": guard.get("errors", [])})
    write_json(REPORT_DIR / "latest.json", account)
    write_json(REPORT_DIR / "positions_latest.json", {"timestamp": timestamp, "positions": positions})
    write_json(REPORT_DIR / "open_orders_latest.json", {"timestamp": timestamp, "open_orders": open_orders})
    write_json(REPORT_DIR / "daily_summary_latest.json", {"timestamp": timestamp, **daily})
    write_daily_report(diagnostic)
    print(json.dumps({"account": account, "daily_summary": daily, "daily_diagnostic": diagnostic}, indent=2, sort_keys=True))
    return 0


def account_from_guard_and_pnl(guard: dict[str, Any], pnl: dict[str, str]) -> dict[str, Any]:
    return {
        "source": "account_reports",
        "account": first_present(guard.get("account"), pnl.get("account")),
        "currency": pnl.get("currency"),
        "daily_pnl": float_or_none(pnl.get("daily_pnl")),
        "realized_pnl": float_or_none(pnl.get("realized_pnl")),
        "unrealized_pnl": float_or_none(pnl.get("unrealized_pnl")),
        "net_liquidation": float_or_none(pnl.get("net_liquidation")),
        "cash": float_or_none(pnl.get("total_cash_value")),
        "buying_power": float_or_none(pnl.get("buying_power")),
        "available_funds": float_or_none(pnl.get("available_funds")),
        "excess_liquidity": float_or_none(pnl.get("excess_liquidity")),
        "gross_position_value": float_or_none(pnl.get("gross_position_value")),
        "pnl_timestamp": pnl.get("timestamp"),
    }


def latest_pnl_row() -> dict[str, str]:
    path = REPORT_ROOT / "pnl_timeseries.csv"
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
    trading_day = recent_complete_trading_day()
    requests = audit_requests_for_date(trading_day)
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
        "trading_date": trading_day.isoformat(),
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


def daily_diagnostic_report(account_state: Any, readiness: dict[str, Any]) -> dict[str, Any]:
    trading_day = recent_complete_trading_day()
    start = datetime.combine(trading_day, datetime.min.time(), tzinfo=NEW_YORK).astimezone(timezone.utc)
    end = datetime.now(timezone.utc)
    metrics = audit_metrics(start, end)
    snapshot = account_state_payload_without_sensitive_id(account_state)
    quote_rows = [row for row in readiness.get("blocking_reasons", [])]
    lifecycle = latest_lifecycle()
    return {
        "timestamp": end.isoformat(),
        "source": "daily_trading_diagnostic_report",
        "report_only": True,
        "date_utc": end.date().isoformat(),
        "trading_date": trading_day.isoformat(),
        "trading_timezone": "America/New_York",
        "account_snapshot": snapshot,
        "lifecycle_funnel": metrics,
        "data_quality": {
            "account_execution_ready": readiness.get("account_execution_ready"),
            "quotes_ready": readiness.get("quotes_ready"),
            "positions_ready": readiness.get("positions_ready"),
            "open_orders_ready": readiness.get("open_orders_ready"),
            "pnl_ready": readiness.get("pnl_ready"),
            "protection_coverage_ready": readiness.get("protection_coverage_ready"),
            "blocking_reasons": readiness.get("blocking_reasons", []),
            "quote_blockers": quote_rows,
        },
        "runtime": lifecycle,
        "mode9_should_run": bool(readiness.get("account_execution_ready")) and lifecycle.get("ibkr_connected") is True,
        "orders_submitted_by_report": 0,
        "orders_cancelled_by_report": 0,
    }


def audit_metrics(start: datetime, end: datetime) -> dict[str, Any]:
    db = AUDIT_DB
    if not db.exists():
        return empty_metrics()
    start_text, end_text = start.isoformat(), end.isoformat()
    uri = f"file:{db}?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True)
    try:
        return {
            "signals": table_count(con, "strategy_signals", "timestamp_utc", start_text, end_text),
            "strategy_decisions": table_count(con, "strategy_decisions", "timestamp", start_text, end_text),
            "order_intents": table_count(con, "order_intent_events", "timestamp_utc", start_text, end_text),
            "risk_checks": table_count(con, "risk_events", "timestamp", start_text, end_text),
            "risk_rejected": table_count_where(con, "risk_events", "timestamp", start_text, end_text, "json_valid(payload_json) AND (json_extract(payload_json, '$.approved') = 0 OR json_extract(payload_json, '$.execution_allowed') = 0)"),
            "submitted": table_count(con, "order_requests", "created_at", start_text, end_text),
            "broker_ack": table_count(con, "broker_orders", "first_seen_at", start_text, end_text),
            "partial_fill": table_count_where(con, "broker_orders", "first_seen_at", start_text, end_text, "filled > 0 AND remaining > 0"),
            "filled": table_count_where(con, "broker_orders", "first_seen_at", start_text, end_text, "completed = 1 OR upper(canonical_status) = 'FILLED' OR upper(status) = 'FILLED'"),
            "executions": table_count(con, "executions", "executed_at", start_text, end_text),
            "commissions": table_count(con, "commission_events", "timestamp_utc", start_text, end_text),
            "quote_blocks": table_count_where(con, "quote_readiness_events", "timestamp", start_text, end_text, "execution_allowed = 0"),
        }
    finally:
        con.close()


def empty_metrics() -> dict[str, int]:
    return {key: 0 for key in ["signals", "strategy_decisions", "order_intents", "risk_checks", "risk_rejected", "submitted", "broker_ack", "partial_fill", "filled", "executions", "commissions", "quote_blocks"]}


def table_count(con: sqlite3.Connection, table: str, column: str, start: str, end: str) -> int:
    return table_count_where(con, table, column, start, end, "1 = 1")


def table_count_where(con: sqlite3.Connection, table: str, column: str, start: str, end: str, predicate: str) -> int:
    try:
        value = con.execute(f"SELECT count(*) FROM {table} WHERE {column} >= ? AND {column} < ? AND {predicate}", (start, end)).fetchone()[0]
    except sqlite3.OperationalError:
        return 0
    return int(value or 0)


def latest_lifecycle() -> dict[str, Any]:
    path = REPORT_ROOT / "autonomous_agent" / "latest.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return {
        "lifecycle_state": payload.get("lifecycle_state"),
        "mode9_running": bool(payload.get("agent_running")),
        "market_session_state": payload.get("market_session_state"),
        "expected_live_bid_ask": (payload.get("market_session") or {}).get("expected_live_bid_ask") if isinstance(payload.get("market_session"), dict) else None,
        "ibkr_connected": payload.get("ibkr_connected"),
        "execution_enabled": payload.get("execution_enabled"),
        "blocked_reason": payload.get("blocked_reason"),
        "safe_mode": payload.get("lifecycle_state") == "SAFE_MODE",
    }


def account_state_payload_without_sensitive_id(account_state: Any) -> dict[str, Any]:
    snapshot = getattr(account_state, "account_snapshot", None)
    if snapshot is None:
        return {}
    from dataclasses import asdict

    return asdict(snapshot)


def write_daily_report(payload: dict[str, Any]) -> None:
    DAILY_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    write_json(DAILY_REPORT_DIR / "latest.json", payload)
    (DAILY_REPORT_DIR / "latest.md").write_text(render_daily_markdown(payload), encoding="utf-8")


def render_daily_markdown(payload: dict[str, Any]) -> str:
    return render_daily_report_markdown(payload)


def audit_requests_for_date(day: object) -> list[dict[str, Any]]:
    db = AUDIT_DB
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
                created_date = datetime.fromisoformat(created_at).astimezone(NEW_YORK).date()
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


def first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def recent_complete_trading_day(now_utc: datetime | None = None) -> object:
    now_utc = now_utc or datetime.now(timezone.utc)
    now_ny = now_utc.astimezone(NEW_YORK)
    trading_day = now_ny.date()
    if now_ny.time() < time(17, 0):
        trading_day -= timedelta(days=1)
    while trading_day.weekday() >= 5:
        trading_day -= timedelta(days=1)
    return trading_day


if __name__ == "__main__":
    raise SystemExit(main())
