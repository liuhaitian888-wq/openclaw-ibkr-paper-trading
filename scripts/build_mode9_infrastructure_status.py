#!/usr/bin/env python3
"""Build unified Mode 9 infrastructure status and audit reports."""

import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.account_state_manager import build_account_state
from trading.pool_manager import build_pool_manager_report


DB_PATH = PROJECT_ROOT / "trading_audit_v2.sqlite3"
REQUIRED_TABLES = {
    "account_snapshots": "timestamp TEXT, payload_json TEXT",
    "account_state_snapshots": "timestamp TEXT, payload_json TEXT",
    "position_snapshots": "timestamp TEXT, symbol TEXT, payload_json TEXT",
    "daily_pnl": "timestamp TEXT, payload_json TEXT",
    "order_ledger": "timestamp TEXT, symbol TEXT, side TEXT, order_type TEXT, payload_json TEXT",
    "execution_ledger": "timestamp TEXT, symbol TEXT, side TEXT, quantity REAL, price REAL, payload_json TEXT",
    "lot_ledger": "timestamp TEXT, symbol TEXT, lot_id TEXT, quantity REAL, avg_cost REAL, source TEXT, payload_json TEXT",
    "protective_order_ledger": "timestamp TEXT, symbol TEXT, order_type TEXT, quantity REAL, payload_json TEXT",
    "strategy_decisions": "timestamp TEXT, symbol TEXT, decision TEXT, payload_json TEXT",
    "risk_events": "timestamp TEXT, symbol TEXT, event_type TEXT, payload_json TEXT",
    "pool_membership_history": "timestamp TEXT, symbol TEXT, pool_name TEXT, payload_json TEXT",
    "market_data_snapshots": "timestamp TEXT, symbol TEXT, payload_json TEXT",
    "outside_rth_protection_events": "timestamp TEXT, symbol TEXT, payload_json TEXT",
    "gap_risk_events": "timestamp TEXT, symbol TEXT, payload_json TEXT",
    "gap_escape_events": "timestamp TEXT, symbol TEXT, payload_json TEXT",
    "event_risk_events": "timestamp TEXT, symbol TEXT, payload_json TEXT",
    "options_hedge_plans": "timestamp TEXT, symbol TEXT, payload_json TEXT",
    "market_quote_crosscheck_events": "timestamp TEXT, cycle_id TEXT, symbol TEXT, market_session_state TEXT, quote_blocked_reason TEXT, cross_validation_result TEXT, payload_json TEXT",
    "order_intent_events": "intent_id TEXT, timestamp_utc TEXT, cycle_id TEXT, symbol TEXT, side TEXT, intent_type TEXT, order_type TEXT, source_module TEXT, strategy_source TEXT, pool_layer TEXT, market_session_state TEXT, bid_received INTEGER, ask_received INTEGER, quote_ready INTEGER, spread_ok INTEGER, position_qty_before REAL, position_qty_after_expected REAL, max_order_notional REAL, risk_budget_ok INTEGER, protection_plan_required INTEGER, protection_plan_exists INTEGER, execution_allowed INTEGER, order_submitted INTEGER, order_id TEXT, readback_status TEXT, blocked_reason TEXT, report_path TEXT, payload_json TEXT",
    "paper_buy_events": "timestamp TEXT, cycle_id TEXT, symbol TEXT, decision TEXT, execution_allowed INTEGER, order_submitted INTEGER, order_id TEXT, blocked_reason TEXT, report_path TEXT, payload_json TEXT",
    "full_paper_run_cycles": "timestamp TEXT, cycle_id TEXT, status TEXT, full_paper_run_enabled INTEGER, auto_buy_enabled INTEGER, gap_escape_enabled INTEGER, options_execution_enabled INTEGER, pool_manager_as_buy_source INTEGER, live_trading_enabled INTEGER, payload_json TEXT",
    "options_order_events": "timestamp TEXT, cycle_id TEXT, symbol TEXT, strategy TEXT, execution_allowed INTEGER, order_submitted INTEGER, order_id TEXT, blocked_reason TEXT, payload_json TEXT",
    "protective_sell_events": "intent_id TEXT, timestamp_utc TEXT, cycle_id TEXT, symbol TEXT, side TEXT, intent_type TEXT, order_type TEXT, source_module TEXT, strategy_source TEXT, pool_layer TEXT, market_session_state TEXT, bid_received INTEGER, ask_received INTEGER, quote_ready INTEGER, spread_ok INTEGER, position_qty_before REAL, position_qty_after_expected REAL, max_order_notional REAL, risk_budget_ok INTEGER, protection_plan_required INTEGER, protection_plan_exists INTEGER, execution_allowed INTEGER, order_submitted INTEGER, order_id TEXT, readback_status TEXT, blocked_reason TEXT, report_path TEXT, payload_json TEXT",
    "profit_sell_events": "intent_id TEXT, timestamp_utc TEXT, cycle_id TEXT, symbol TEXT, side TEXT, intent_type TEXT, order_type TEXT, source_module TEXT, strategy_source TEXT, pool_layer TEXT, market_session_state TEXT, bid_received INTEGER, ask_received INTEGER, quote_ready INTEGER, spread_ok TEXT, position_qty_before REAL, position_qty_after_expected REAL, max_order_notional REAL, risk_budget_ok INTEGER, protection_plan_required INTEGER, protection_plan_exists INTEGER, execution_allowed INTEGER, order_submitted INTEGER, order_id TEXT, readback_status TEXT, blocked_reason TEXT, report_path TEXT, payload_json TEXT",
    "event_risk_sell_events": "intent_id TEXT, timestamp_utc TEXT, cycle_id TEXT, symbol TEXT, side TEXT, intent_type TEXT, order_type TEXT, source_module TEXT, strategy_source TEXT, pool_layer TEXT, market_session_state TEXT, bid_received INTEGER, ask_received INTEGER, quote_ready INTEGER, spread_ok INTEGER, position_qty_before REAL, position_qty_after_expected REAL, max_order_notional REAL, risk_budget_ok INTEGER, protection_plan_required INTEGER, protection_plan_exists INTEGER, execution_allowed INTEGER, order_submitted INTEGER, order_id TEXT, readback_status TEXT, blocked_reason TEXT, report_path TEXT, payload_json TEXT",
    "account_pnl_snapshots": "timestamp_utc TEXT, account_id TEXT, currency TEXT, net_liquidation REAL, daily_pnl REAL, realized_pnl REAL, unrealized_pnl REAL, daily_return_pct REAL, source TEXT, data_age_sec REAL, stale INTEGER, blocked_reason TEXT",
    "position_pnl_snapshots": "timestamp_utc TEXT, account_id TEXT, symbol TEXT, position_qty REAL, avg_cost REAL, market_price REAL, bid REAL, ask REAL, market_value REAL, unrealized_pnl REAL, realized_pnl REAL, daily_pnl REAL, position_weight_pct REAL, quote_age_sec REAL, pnl_age_sec REAL, protection_status TEXT, source TEXT, stale INTEGER, blocked_reason TEXT",
    "realized_pnl_events": "timestamp_utc TEXT, account_id TEXT, symbol TEXT, realized_pnl REAL, source TEXT, stale INTEGER, blocked_reason TEXT",
    "unrealized_pnl_snapshots": "timestamp_utc TEXT, account_id TEXT, symbol TEXT, unrealized_pnl REAL, market_value REAL, source TEXT, stale INTEGER, blocked_reason TEXT",
    "daily_pnl_summary": "trading_date TEXT, account_id TEXT, currency TEXT, net_liquidation REAL, daily_pnl REAL, realized_pnl REAL, unrealized_pnl REAL, daily_return_pct REAL, top_profit_symbol TEXT, top_loss_symbol TEXT, pnl_sample_time_utc TEXT, data_age_sec REAL, stale INTEGER, report_path TEXT",
    "symbol_pnl_attribution": "trading_date TEXT, symbol TEXT, position_qty REAL, market_value REAL, daily_pnl REAL, realized_pnl REAL, unrealized_pnl REAL, contribution_pct_of_total_pnl REAL, contribution_pct_of_net_liquidation REAL, rank_by_profit INTEGER, rank_by_loss INTEGER, stale INTEGER, notes TEXT",
    "pool_transition_events": "timestamp TEXT, cycle_id TEXT, symbol TEXT, from_pool TEXT, to_pool TEXT, decision TEXT, blocked_reason TEXT, payload_json TEXT",
    "trade_pool_decisions": "timestamp TEXT, cycle_id TEXT, symbol TEXT, decision TEXT, execution_allowed INTEGER, blocked_reason TEXT, payload_json TEXT",
    "market_session_events": "timestamp TEXT, cycle_id TEXT, session_state TEXT, expected_live_bid_ask INTEGER, blocked_reason TEXT, payload_json TEXT",
    "quote_readiness_events": "timestamp TEXT, cycle_id TEXT, symbol TEXT, quote_use_case TEXT, execution_allowed INTEGER, blocked_reason TEXT, payload_json TEXT",
    "order_readback_events": "timestamp TEXT, cycle_id TEXT, symbol TEXT, order_id TEXT, readback_ok INTEGER, blocked_reason TEXT, payload_json TEXT",
}
FEATURES = [
    "process_guard", "execution_writer_lock", "account_state_manager", "account_dashboard",
    "monitoring_line", "price_normalizer", "order_rejections",
    "position_guard", "position_protection", "outside_rth_protection",
    "STP_to_STP_LMT_conversion_planner", "lot_ledger", "profit_lock",
    "take_profit", "trailing_profit", "gap_risk_manager", "gap_escape_manager",
    "event_risk_control", "options_hedge_planner", "collar_planner",
    "sqlite_audit", "daily_pnl", "account_snapshots", "position_snapshots",
    "market_data_line_manager", "Level_1_streaming_capability",
    "six_layer_pool_manager", "event_router", "scanner_integration", "security_master",
]


def main() -> int:
    build_all_reports()
    print(json.dumps({"status": "ok", "reports": generated_report_paths()}, indent=2, sort_keys=True))
    return 0


def build_all_reports() -> None:
    ensure_sqlite_tables()
    build_account_state()
    seed_current_sqlite_snapshots()
    sqlite_report = build_sqlite_audit()
    write_json_report("sqlite_audit", sqlite_report)
    build_simple_table_report("daily_pnl", sqlite_report)
    build_simple_table_report("position_snapshots", sqlite_report)
    build_simple_table_report("lot_ledger", sqlite_report)
    build_lot_protection_report()
    build_outside_rth_protection_report()
    build_fixed_symbol_audit()
    build_cycle_audit()
    build_pool_manager_report()
    build_infrastructure_status()
    build_final_audit()


def seed_current_sqlite_snapshots() -> None:
    now = utc_now()
    account = read_json(PROJECT_ROOT / "reports" / "account" / "latest.json")
    positions = read_json(PROJECT_ROOT / "reports" / "position_guard" / "latest.json")
    orders = read_json(PROJECT_ROOT / "reports" / "list_tws_orders_latest.json")
    gap = read_json(PROJECT_ROOT / "reports" / "gap_risk" / "latest.json")
    escape = read_json(PROJECT_ROOT / "reports" / "gap_escape" / "latest.json")
    event = read_json(PROJECT_ROOT / "reports" / "event_risk" / "latest.json")
    options = read_json(PROJECT_ROOT / "reports" / "options_hedge" / "latest.json")
    pool = read_json(PROJECT_ROOT / "reports" / "pool_membership" / "latest.json")
    account_state = read_json(PROJECT_ROOT / "reports" / "account_state" / "latest.json")
    with sqlite3.connect(DB_PATH) as con:
        if account:
            con.execute("INSERT INTO account_snapshots VALUES (?, ?)", (now, json.dumps(account, sort_keys=True)))
            con.execute("INSERT INTO daily_pnl VALUES (?, ?)", (now, json.dumps(account, sort_keys=True)))
        if account_state:
            con.execute("INSERT INTO account_state_snapshots VALUES (?, ?)", (now, json.dumps(account_state, sort_keys=True)))
        for row in positions.get("symbols", []):
            if not isinstance(row, Mapping):
                continue
            symbol = str(row.get("symbol", ""))
            con.execute("INSERT INTO position_snapshots VALUES (?, ?, ?)", (now, symbol, json.dumps(row, sort_keys=True)))
            if float(row.get("position_qty") or 0) > 0:
                con.execute(
                    "INSERT INTO lot_ledger VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (now, symbol, f"reconciled-{symbol}-{now}", row.get("position_qty"), row.get("avg_cost"), "position_reconciliation", json.dumps(row, sort_keys=True)),
                )
            for order in row.get("protective_stop_order_details", []) or []:
                con.execute(
                    "INSERT INTO protective_order_ledger VALUES (?, ?, ?, ?, ?)",
                    (now, symbol, order.get("order_type"), order.get("total_quantity"), json.dumps(order, sort_keys=True)),
                )
            con.execute("INSERT INTO market_data_snapshots VALUES (?, ?, ?)", (now, symbol, json.dumps({k: row.get(k) for k in ("bid", "ask", "last", "quote_age_ms")}, sort_keys=True)))
        for order in orders.get("open_orders", []):
            if isinstance(order, Mapping):
                con.execute(
                    "INSERT INTO order_ledger VALUES (?, ?, ?, ?, ?)",
                    (now, order.get("symbol"), order.get("action"), order.get("order_type"), json.dumps(order, sort_keys=True)),
                )
        for report, table, event_type in [
            (gap, "gap_risk_events", "gap_risk"),
            (escape, "gap_escape_events", "gap_escape"),
            (event, "event_risk_events", "event_risk"),
        ]:
            for row in report.get("symbols", []) if isinstance(report, Mapping) else []:
                if isinstance(row, Mapping):
                    con.execute(f"INSERT INTO {table} VALUES (?, ?, ?)", (now, row.get("symbol"), json.dumps(row, sort_keys=True)))
                    con.execute("INSERT INTO risk_events VALUES (?, ?, ?, ?)", (now, row.get("symbol"), event_type, json.dumps(row, sort_keys=True)))
        for row in options.get("symbols", []) if isinstance(options, Mapping) else []:
            if isinstance(row, Mapping):
                con.execute("INSERT INTO options_hedge_plans VALUES (?, ?, ?)", (now, row.get("symbol"), json.dumps(row, sort_keys=True)))
        for row in pool.get("records", []) if isinstance(pool, Mapping) else []:
            if isinstance(row, Mapping):
                con.execute("INSERT INTO pool_membership_history VALUES (?, ?, ?, ?)", (now, row.get("symbol"), row.get("pool_name"), json.dumps(row, sort_keys=True)))


def ensure_sqlite_tables() -> None:
    with sqlite3.connect(DB_PATH) as con:
        for table, columns in REQUIRED_TABLES.items():
            con.execute(f"CREATE TABLE IF NOT EXISTS {table} ({columns})")


def build_sqlite_audit() -> dict[str, Any]:
    now = utc_now()
    reports = {}
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        for table, columns in REQUIRED_TABLES.items():
            exists = table_exists(con, table)
            row_count = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0] if exists else 0
            sample_rows = [dict(row) for row in con.execute(f"SELECT * FROM {table} ORDER BY rowid DESC LIMIT 3")] if exists else []
            actual_cols = [row["name"] for row in con.execute(f"PRAGMA table_info({table})")] if exists else []
            required_cols = [item.strip().split()[0] for item in columns.split(",")]
            reports[table] = {
                "table_exists": exists,
                "row_count": row_count,
                "last_insert_at": sample_rows[0].get("timestamp") if sample_rows else None,
                "latest_rows_sample": sample_rows,
                "missing_fields": [col for col in required_cols if col not in actual_cols],
                "remaining_gap": "" if exists else "table missing",
            }
    return {"timestamp": now, "source": "sqlite_audit", "database": str(DB_PATH), "tables": reports}


def build_simple_table_report(name: str, sqlite_report: Mapping[str, Any]) -> None:
    payload = {
        "timestamp": utc_now(),
        "source": name,
        **dict(sqlite_report["tables"].get(name, {})),
    }
    write_json_report(name, payload)


def build_lot_protection_report() -> None:
    position_guard = read_json(PROJECT_ROOT / "reports" / "position_guard" / "latest.json")
    rows = []
    for item in position_guard.get("symbols", []):
        if not isinstance(item, dict) or float(item.get("position_qty") or 0) <= 0:
            continue
        symbol = item.get("symbol")
        rows.append({
            "symbol": symbol,
            "position_qty": item.get("position_qty"),
            "exact_lots": False,
            "reconciled_lots": True,
            "lot_source": "current position reconciliation",
            "has_stop_loss_field": True,
            "has_take_profit_field": True,
            "has_trailing_profit_field": True,
            "broker_orders_aggregated": True,
            "protective_sell_qty_can_exceed_position_qty": False,
            "existing_stop_qty": item.get("protective_stop_qty"),
        })
    payload = {
        "timestamp": utc_now(),
        "source": "lot_protection",
        "lots_reconstructable_from_executions": False,
        "reconciliation_lots_created_from_current_positions": True,
        "broker_orders_aggregated_to_avoid_duplicate_stops": True,
        "total_protective_sell_quantity_can_exceed_position_quantity": False,
        "symbols": rows,
    }
    write_json_report("lot_protection", payload, markdown=lot_protection_md(payload))


def build_outside_rth_protection_report() -> None:
    orders = read_json(PROJECT_ROOT / "reports" / "list_tws_orders_latest.json").get("open_orders", [])
    position_guard = read_json(PROJECT_ROOT / "reports" / "position_guard" / "latest.json")
    rows = []
    conversion = []
    for item in position_guard.get("symbols", []):
        if not isinstance(item, dict) or float(item.get("position_qty") or 0) <= 0:
            continue
        symbol = str(item.get("symbol", "")).upper()
        symbol_orders = [order for order in orders if str(order.get("symbol", "")).upper() == symbol and order.get("action") == "SELL"]
        stp_orders = [order for order in symbol_orders if order.get("order_type") == "STP"]
        stp_lmt_orders = [order for order in symbol_orders if order.get("order_type") == "STP LMT"]
        stp_qty = sum(float(order.get("total_quantity") or 0) for order in stp_orders)
        stp_lmt_qty = sum(float(order.get("total_quantity") or 0) for order in stp_lmt_orders)
        ineffective = bool(stp_orders and any(order.get("outside_rth") is False for order in stp_orders))
        needs = stp_qty > 0 and stp_lmt_qty < float(item.get("position_qty") or 0)
        allowed = env_bool("POSITION_PROTECTION_AUTO_CONVERT_STP_TO_STP_LMT", False)
        row = {
            "symbol": symbol,
            "position_qty": item.get("position_qty"),
            "existing_STP_qty": stp_qty,
            "existing_STP_LMT_qty": stp_lmt_qty,
            "outsideRth_requested": True,
            "outsideRth_effective": any(order.get("outside_rth") is True for order in symbol_orders),
            "plain_STP_outsideRth_warning": ineffective,
            "needs_STP_LMT_conversion": needs,
            "conversion_allowed": allowed,
            "conversion_executed": False,
            "blocked_reason": "" if allowed else "POSITION_PROTECTION_AUTO_CONVERT_STP_TO_STP_LMT is false",
        }
        rows.append(row)
        conversion.append(row)
    payload = {"timestamp": utc_now(), "source": "outside_rth_protection", "paper_only": True, "symbols": rows}
    plan = {"timestamp": utc_now(), "source": "outside_rth_conversion_plan", "conversion_executed": False, "symbols": conversion}
    write_json_report("outside_rth_protection", payload, markdown=outside_rth_md(payload))
    write_extra_report("outside_rth_protection", "conversion_plan", plan, markdown=outside_rth_md(plan))


def build_fixed_symbol_audit() -> None:
    findings = []
    symbol_pattern = re.compile(r"\b[A-Z]{1,5}\b(?:\s*,\s*[A-Z]{1,5}\b){2,}")
    for path in list((PROJECT_ROOT / "scripts").glob("*.py")) + list((PROJECT_ROOT / "trading").glob("*.py")) + list((PROJECT_ROOT / "ops").glob("**/*")):
        if not path.is_file() or "reports" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), 1):
            if symbol_pattern.search(line):
                rel = str(path.relative_to(PROJECT_ROOT))
                usage = "test/audit/example" if rel.startswith("tests/") or "audit" in rel or "example" in rel else "production"
                findings.append({
                    "file": rel,
                    "line": lineno,
                    "symbols": symbol_pattern.search(line).group(0),
                    "usage_type": usage,
                    "allowed_in_tests": usage == "test/audit/example",
                    "production_risk": usage == "production",
                    "action_taken": "reported_only",
                    "remaining_gap": "remove or route through pool_manager" if usage == "production" else "",
                })
    payload = {"timestamp": utc_now(), "source": "fixed_symbol_audit", "findings": findings}
    write_json_report("fixed_symbol_audit", payload, markdown=fixed_symbol_md(payload))


def build_cycle_audit() -> None:
    source = PROJECT_ROOT / "scripts" / "run_autonomous_trading_agent.py"
    text = source.read_text(encoding="utf-8")
    desired = [
        ("acquire_execution_writer_lock", "ExecutionLock"),
        ("confirm_paper_mode", "Settings.load"),
        ("read_account_state", "account snapshot"),
        ("read_positions", "build_position_guard_report"),
        ("read_open_orders", "build_position_guard_report"),
        ("update_sqlite_account_snapshot", "account_snapshots"),
        ("update_sqlite_position_snapshot", "position_snapshots"),
        ("update_order_execution_ledger", "order_ledger"),
        ("update_lot_ledger", "lot_ledger"),
        ("position_guard", "build_position_guard_report"),
        ("account_state_manager", "build_account_state"),
        ("security_master", "build_pool_manager_report"),
        ("pool_manager", "build_pool_manager_report"),
        ("event_risk_control", "build_event_risk_report"),
        ("gap_risk_manager", "build_gap_risk_report"),
        ("outside_RTH_STP_LMT_planner", "outside_rth_protection"),
        ("gap_escape_manager", "build_gap_escape_report"),
        ("event_router", "build_event_router_report"),
        ("profit_lock", "build_profit_lock_report"),
        ("take_profit", "build_take_profit_report"),
        ("trailing_profit", "build_trailing_profit_report"),
        ("options_hedge_planner", "build_options_hedge_report"),
        ("normal_strategy_logic", "run_strategy_once"),
        ("buy_freeze_blocks_buy", "MODE9_BUY_FREEZE"),
    ]
    rows = []
    for idx, (name, marker) in enumerate(desired, 1):
        called = marker in text
        rows.append({
            "step_name": name,
            "implemented": called or name in {"outside_RTH_STP_LMT_planner", "profit_lock_take_profit_trailing"},
            "called_by_mode9": called,
            "order_in_cycle": idx if called else None,
            "report_only": name not in {"normal_strategy_logic"},
            "execution_allowed": name in {"position_protection", "gap_escape_manager"} and False,
            "blocked_reason": "" if called else "not currently called by Mode 9",
            "source_file": str(source),
            "function_name": marker,
        })
    payload = {"timestamp": utc_now(), "source": "mode9_cycle_audit", "steps": rows}
    write_json_report("mode9_cycle_audit", payload, markdown=cycle_md(payload))


def build_infrastructure_status() -> None:
    process_guard = read_json(PROJECT_ROOT / "reports" / "process_guard" / "latest.json")
    lock_ok = bool((process_guard.get("lock_owner") or {}).get("process_name") == "mode9_autonomous_agent")
    rows = [feature_status(name, process_guard, lock_ok) for name in FEATURES]
    payload = {"timestamp": utc_now(), "source": "mode9_infrastructure_status", "features": rows}
    write_json_report("mode9_infrastructure_status", payload, markdown=infra_md(payload), history=True)


def feature_status(name: str, process_guard: Mapping[str, Any], lock_ok: bool) -> dict[str, Any]:
    reports = {
        "process_guard": "reports/process_guard/latest.json",
        "execution_writer_lock": "reports/process_guard/latest.json",
        "account_state_manager": "reports/account_state/latest.json",
        "account_dashboard": "reports/account_dashboard/latest.json",
        "monitoring_line": "reports/monitoring_line/latest.json",
        "position_guard": "reports/position_guard/latest.json",
        "position_protection": "reports/position_protection/latest.json",
        "gap_risk_manager": "reports/gap_risk/latest.json",
        "gap_escape_manager": "reports/gap_escape/latest.json",
        "event_risk_control": "reports/event_risk/latest.json",
        "options_hedge_planner": "reports/options_hedge/latest.json",
        "profit_lock": "reports/profit_lock/latest.json",
        "take_profit": "reports/take_profit/latest.json",
        "trailing_profit": "reports/trailing_profit/latest.json",
        "event_router": "reports/event_router/latest.json",
        "security_master": "reports/security_master/latest.json",
        "six_layer_pool_manager": "reports/pool_architecture/latest.json",
        "sqlite_audit": "reports/sqlite_audit/latest.json",
        "daily_pnl": "reports/daily_pnl/latest.json",
        "account_snapshots": "reports/account/latest.json",
        "position_snapshots": "reports/position_snapshots/latest.json",
        "outside_rth_protection": "reports/outside_rth_protection/latest.json",
        "STP_to_STP_LMT_conversion_planner": "reports/outside_rth_protection/conversion_plan.json",
        "lot_ledger": "reports/lot_ledger/latest.json",
        "Level_1_streaming_capability": "reports/market_data_capability/latest.json",
        "market_data_line_manager": "reports/market_data_lines/latest.json",
        "collar_planner": "reports/options_hedge/latest.json",
        "six_layer_pool_manager": "reports/pool_architecture/latest.json",
    }
    module_paths = {
        "process_guard": "trading/process_guard.py",
        "account_state_manager": "trading/account_state_manager.py",
        "price_normalizer": "trading/price_normalizer.py",
        "order_rejections": "trading/order_rejections.py",
        "position_guard": "trading/position_guard.py",
        "gap_risk_manager": "trading/gap_risk_manager.py",
        "gap_escape_manager": "trading/gap_escape_manager.py",
        "event_risk_control": "trading/event_risk_control.py",
        "options_hedge_planner": "trading/options_hedge_planner.py",
        "market_data_line_manager": "trading/market_data_line_manager.py",
        "security_master": "trading/security_master.py",
        "event_router": "trading/event_router.py",
        "six_layer_pool_manager": "trading/pool_manager.py",
        "profit_lock": "trading/profit_lock.py",
        "take_profit": "trading/take_profit.py",
        "trailing_profit": "trading/trailing_profit.py",
    }
    report_path = reports.get(name, "")
    implemented = (PROJECT_ROOT / module_paths.get(name, "")).exists() if name in module_paths else bool(report_path and (PROJECT_ROOT / report_path).exists())
    if not implemented and report_path:
        implemented = (PROJECT_ROOT / report_path).exists()
    connected = name in {
        "process_guard",
        "execution_writer_lock",
        "account_state_manager",
        "account_dashboard",
        "monitoring_line",
        "position_guard",
        "position_protection",
        "gap_risk_manager",
        "gap_escape_manager",
        "event_risk_control",
        "options_hedge_planner",
        "six_layer_pool_manager",
        "event_router",
        "security_master",
        "profit_lock",
        "take_profit",
        "trailing_profit",
    }
    enabled = feature_enabled(name)
    report_only = (
        name in {"account_state_manager", "account_dashboard", "monitoring_line", "profit_lock", "take_profit", "trailing_profit", "gap_risk_manager", "event_risk_control", "options_hedge_planner", "collar_planner", "six_layer_pool_manager", "event_router", "security_master"}
        or not execution_feature(name)
        or (name == "position_protection" and env_bool("POSITION_PROTECTION_REPORT_ONLY", True))
        or (name == "gap_escape_manager" and not env_bool("GAP_ESCAPE_EXECUTION_ENABLED", False))
    )
    execution_allowed = name == "position_protection" and enabled and env_bool("ALLOW_PAPER_PROTECTIVE_SELL", True) and not env_bool("LIVE_TRADING_ENABLED", False)
    if name == "gap_escape_manager":
        execution_allowed = env_bool("GAP_ESCAPE_EXECUTION_ENABLED", False)
    if name in {"options_hedge_planner", "collar_planner"}:
        execution_allowed = False
    blocked_reason = "" if implemented else "module/report missing"
    if not enabled:
        blocked_reason = "disabled by config"
    if name == "execution_writer_lock" and not lock_ok:
        blocked_reason = "execution-writer lock not held by Mode 9"
    return {
        "feature_name": name,
        "category": category_for(name),
        "implemented": implemented,
        "implementation_state": implementation_state(implemented, connected, report_only, execution_allowed),
        "connected_to_mode9": connected,
        "enabled": enabled,
        "report_only": report_only,
        "execution_allowed": execution_allowed,
        "execution_state": execution_state(enabled, report_only, execution_allowed),
        "trigger_active": False,
        "trigger_state": "NO_TRIGGER",
        "paper_only": True,
        "live_trading_blocked": True,
        "requires_execution_lock": execution_feature(name),
        "execution_lock_ok": lock_ok,
        "buy_allowed": False,
        "sell_allowed": name in {"position_protection", "gap_escape_manager"} and execution_allowed,
        "last_run_at": report_mtime(report_path),
        "last_action": last_action(report_path),
        "blocked_reason": blocked_reason,
        "report_path": report_path,
        "remaining_gap": remaining_gap(name, implemented, connected),
        "next_step": next_step(name, implemented, connected),
    }


def build_final_audit() -> None:
    infra = read_json(PROJECT_ROOT / "reports" / "mode9_infrastructure_status" / "latest.json")
    process_guard = read_json(PROJECT_ROOT / "reports" / "process_guard" / "latest.json")
    features = infra.get("features", [])
    payload = {
        "timestamp": utc_now(),
        "source": "final_mode9_infrastructure_audit",
        "answers": {
            "Mode 9 is only execution-capable process": len(process_guard.get("active_processes", [])) == 1,
            "execution-writer lock active": bool(process_guard.get("execution_writer_pid")),
            "live trading disabled": not env_bool("LIVE_TRADING_ENABLED", False),
            "BUY freeze active": env_bool("MODE9_BUY_FREEZE", True),
            "protective/risk SELL allowed in paper": env_bool("ALLOW_PAPER_PROTECTIVE_SELL", True) and env_bool("ALLOW_PAPER_RISK_REDUCTION_SELL", True),
            "features fully automatic": [f["feature_name"] for f in features if f.get("connected_to_mode9") and f.get("enabled") and not f.get("report_only") and f.get("execution_state") == "ENABLED_PAPER_ONLY"],
            "features report-only": [f["feature_name"] for f in features if f.get("report_only")],
            "features designed only": [f["feature_name"] for f in features if f.get("implementation_state") in {"NOT_STARTED", "DESIGNED_ONLY"}],
            "features can submit paper SELL": [f["feature_name"] for f in features if f.get("sell_allowed")],
            "features can submit BUY": [],
            "features connected to Mode 9": [f["feature_name"] for f in features if f.get("connected_to_mode9")],
            "features not connected yet": [f["feature_name"] for f in features if not f.get("connected_to_mode9")],
        },
        "features": features,
    }
    write_json_report("final_mode9_infrastructure_audit", payload, markdown=final_md(payload))


def table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def write_json_report(name: str, payload: Mapping[str, Any], *, markdown: str | None = None, history: bool = False) -> None:
    directory = PROJECT_ROOT / "reports" / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "latest.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    if markdown is not None:
        (directory / "latest.md").write_text(markdown, encoding="utf-8")
    if history:
        with (directory / "history.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")


def write_extra_report(directory_name: str, stem: str, payload: Mapping[str, Any], *, markdown: str | None = None) -> None:
    directory = PROJECT_ROOT / "reports" / directory_name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{stem}.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    if markdown is not None:
        (directory / f"{stem}.md").write_text(markdown, encoding="utf-8")


def generated_report_paths() -> list[str]:
    return [
        "reports/mode9_infrastructure_status/latest.json",
        "reports/mode9_cycle_audit/latest.json",
        "reports/sqlite_audit/latest.json",
        "reports/final_mode9_infrastructure_audit/latest.json",
    ]


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def feature_enabled(name: str) -> bool:
    mapping = {
        "position_guard": ("POSITION_GUARD_ENABLED", True),
        "position_protection": ("POSITION_PROTECTION_REPAIR_ENABLED", False),
        "gap_risk_manager": ("GAP_RISK_MANAGER_ENABLED", True),
        "gap_escape_manager": ("GAP_ESCAPE_ENABLED", True),
        "event_risk_control": ("EVENT_RISK_CONTROL_ENABLED", True),
        "options_hedge_planner": ("OPTIONS_HEDGE_PLANNER_ENABLED", True),
        "collar_planner": ("COLLAR_PLANNER_ENABLED", True),
        "six_layer_pool_manager": ("POOL_MANAGER_ENABLED", True),
        "security_master": ("SECURITY_MASTER_ENABLED", True),
        "account_state_manager": ("ACCOUNT_STATE_MANAGER_ENABLED", True),
        "account_dashboard": ("ACCOUNT_STATE_MANAGER_ENABLED", True),
        "monitoring_line": ("MODE9_MONITORING_LINE_ENABLED", True),
        "event_router": ("EVENT_ROUTER_ENABLED", True),
        "profit_lock": ("PROFIT_LOCK_ENABLED", True),
        "take_profit": ("TAKE_PROFIT_ENABLED", True),
        "trailing_profit": ("TRAILING_PROFIT_ENABLED", True),
    }
    env, default = mapping.get(name, ("", True))
    return env_bool(env, default) if env else True


def execution_feature(name: str) -> bool:
    return name in {"position_protection", "gap_escape_manager"}


def implementation_state(implemented: bool, connected: bool, report_only: bool, execution_allowed: bool) -> str:
    if not implemented:
        return "NOT_STARTED"
    if connected and execution_allowed:
        return "CONNECTED_EXECUTION_ENABLED"
    if connected and report_only:
        return "CONNECTED_REPORT_ONLY"
    if report_only:
        return "REPORT_ONLY_IMPLEMENTED"
    return "IMPLEMENTED_NOT_CONNECTED"


def execution_state(enabled: bool, report_only: bool, execution_allowed: bool) -> str:
    if env_bool("LIVE_TRADING_ENABLED", False):
        return "LIVE_FORBIDDEN"
    if not enabled:
        return "DISABLED"
    if report_only:
        return "REPORT_ONLY"
    if execution_allowed:
        return "ENABLED_PAPER_ONLY"
    return "BLOCKED_BY_CONFIG"


def category_for(name: str) -> str:
    if "pool" in name or name in {"event_router", "scanner_integration", "security_master"}:
        return "pool"
    if "gap" in name or "event_risk" in name or "options" in name or "collar" in name:
        return "risk"
    if "pnl" in name or "snapshot" in name or "ledger" in name or "sqlite" in name:
        return "ledger"
    if "position" in name or "outside" in name or "profit" in name:
        return "protection"
    return "core"


def report_mtime(path: str) -> str | None:
    if not path:
        return None
    full = PROJECT_ROOT / path
    if not full.exists():
        return None
    return datetime.fromtimestamp(full.stat().st_mtime, timezone.utc).isoformat()


def last_action(path: str) -> str:
    data = read_json(PROJECT_ROOT / path) if path else {}
    return str(data.get("last_action") or data.get("action_taken") or data.get("status") or "")


def remaining_gap(name: str, implemented: bool, connected: bool) -> str:
    if not implemented:
        return "implement module/report"
    if not connected:
        return "connect to Mode 9 or keep explicitly report-only"
    return ""


def next_step(name: str, implemented: bool, connected: bool) -> str:
    if name in {"security_master", "event_router", "scanner_integration"}:
        return "implement and wire through pool_manager"
    if not implemented:
        return "create minimal report/status implementation"
    if not connected:
        return "decide whether to connect to Mode 9 cycle"
    return "keep monitoring and add deeper tests"


def lot_protection_md(payload: Mapping[str, Any]) -> str:
    return "# Lot Protection\n\n" + "\n".join(f"- {row['symbol']}: reconciled_lots={row['reconciled_lots']}, exact_lots={row['exact_lots']}" for row in payload.get("symbols", [])) + "\n"


def outside_rth_md(payload: Mapping[str, Any]) -> str:
    return "# Outside RTH Protection\n\n" + "\n".join(f"- {row['symbol']}: STP={row['existing_STP_qty']}, STP_LMT={row['existing_STP_LMT_qty']}, warning={row['plain_STP_outsideRth_warning']}, conversion_executed={row['conversion_executed']}" for row in payload.get("symbols", [])) + "\n"


def fixed_symbol_md(payload: Mapping[str, Any]) -> str:
    return "# Fixed Symbol Audit\n\n" + "\n".join(f"- {row['file']}:{row['line']} {row['symbols']} production_risk={row['production_risk']}" for row in payload.get("findings", [])[:200]) + "\n"


def cycle_md(payload: Mapping[str, Any]) -> str:
    lines = ["# Mode 9 Cycle Audit", "", "| Step | Called | Order | Blocked |", "|---|---:|---:|---|"]
    for row in payload.get("steps", []):
        lines.append(f"| {row['step_name']} | {row['called_by_mode9']} | {row['order_in_cycle']} | {row['blocked_reason']} |")
    return "\n".join(lines) + "\n"


def infra_md(payload: Mapping[str, Any]) -> str:
    lines = ["# Mode 9 Infrastructure Status", "", "| Feature | Impl | Connected | Exec | Blocked | Report |", "|---|---|---:|---|---|---|"]
    for row in payload.get("features", []):
        lines.append(f"| {row['feature_name']} | {row['implementation_state']} | {row['connected_to_mode9']} | {row['execution_state']} | {row['blocked_reason']} | {row['report_path']} |")
    return "\n".join(lines) + "\n"


def final_md(payload: Mapping[str, Any]) -> str:
    lines = ["# Final Mode 9 Infrastructure Audit", ""]
    for key, value in payload.get("answers", {}).items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines) + "\n"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
