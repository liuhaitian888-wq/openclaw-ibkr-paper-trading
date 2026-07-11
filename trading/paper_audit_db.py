"""SQLite logging helpers for Mode 9 paper automation."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from trading.config import PROJECT_ROOT


DB_PATH = PROJECT_ROOT / "trading_audit.sqlite3"

ORDER_INTENT_COLUMNS = (
    "event_id TEXT, intent_id TEXT, timestamp_utc TEXT, cycle_id TEXT, snapshot_id TEXT, state_version INTEGER, "
    "state_version_min INTEGER, state_version_max INTEGER, symbol TEXT, side TEXT, intent_type TEXT, order_type TEXT, "
    "source_signal_id TEXT, source_trigger_id TEXT, source_module TEXT, strategy_source TEXT, pool_layer TEXT, "
    "market_session_state TEXT, bid_received INTEGER, ask_received INTEGER, quote_ready INTEGER, spread_ok INTEGER, "
    "position_qty_before REAL, position_qty_after_expected REAL, max_order_notional REAL, risk_budget_ok INTEGER, "
    "protection_plan_required INTEGER, protection_plan_exists INTEGER, protection_plan_mode TEXT, protection_plan_status TEXT, "
    "protection_intent_id TEXT, protection_due_by TEXT, execution_allowed INTEGER, simulated_order_submitted INTEGER, "
    "ibkr_paper_order_submitted INTEGER, live_order_submitted INTEGER, order_submitted INTEGER, order_id TEXT, "
    "readback_status TEXT, blocked_reason TEXT, report_path TEXT, payload_json TEXT"
)

PAPER_AUTOMATION_TABLES: dict[str, str] = {
    "order_intent_events": ORDER_INTENT_COLUMNS,
    "market_quote_crosscheck_events": "timestamp TEXT, cycle_id TEXT, symbol TEXT, market_session_state TEXT, quote_blocked_reason TEXT, cross_validation_result TEXT, payload_json TEXT",
    "paper_buy_events": "timestamp TEXT, cycle_id TEXT, symbol TEXT, pool_layer TEXT, inclusion_reason TEXT, blocked_reason TEXT, market_session_state TEXT, expected_live_bid_ask INTEGER, bid_received INTEGER, ask_received INTEGER, quote_ready INTEGER, spread_ok INTEGER, event_risk_ok INTEGER, gap_risk_ok INTEGER, position_sizing_ok INTEGER, decision TEXT, execution_allowed INTEGER, order_submitted INTEGER, order_id TEXT, readback_status TEXT, report_path TEXT, payload_json TEXT",
    "full_paper_run_cycles": "timestamp TEXT, cycle_id TEXT, status TEXT, full_paper_run_enabled INTEGER, auto_buy_enabled INTEGER, gap_escape_enabled INTEGER, options_execution_enabled INTEGER, pool_manager_as_buy_source INTEGER, live_trading_enabled INTEGER, payload_json TEXT",
    "options_order_events": "timestamp TEXT, cycle_id TEXT, symbol TEXT, strategy TEXT, event_type TEXT, execution_allowed INTEGER, order_submitted INTEGER, order_id TEXT, readback_status TEXT, blocked_reason TEXT, payload_json TEXT",
    "protective_sell_events": ORDER_INTENT_COLUMNS,
    "gap_escape_events": ORDER_INTENT_COLUMNS,
    "profit_sell_events": ORDER_INTENT_COLUMNS,
    "event_risk_sell_events": ORDER_INTENT_COLUMNS,
    "account_pnl_snapshots": "timestamp_utc TEXT, account_id TEXT, currency TEXT, net_liquidation REAL, daily_pnl REAL, realized_pnl REAL, unrealized_pnl REAL, daily_return_pct REAL, source TEXT, data_age_sec REAL, stale INTEGER, blocked_reason TEXT",
    "position_pnl_snapshots": "timestamp_utc TEXT, account_id TEXT, symbol TEXT, position_qty REAL, avg_cost REAL, market_price REAL, bid REAL, ask REAL, market_value REAL, unrealized_pnl REAL, realized_pnl REAL, daily_pnl REAL, position_weight_pct REAL, quote_age_sec REAL, pnl_age_sec REAL, protection_status TEXT, source TEXT, stale INTEGER, blocked_reason TEXT",
    "realized_pnl_events": "timestamp_utc TEXT, account_id TEXT, symbol TEXT, realized_pnl REAL, source TEXT, stale INTEGER, blocked_reason TEXT",
    "unrealized_pnl_snapshots": "timestamp_utc TEXT, account_id TEXT, symbol TEXT, unrealized_pnl REAL, market_value REAL, source TEXT, stale INTEGER, blocked_reason TEXT",
    "daily_pnl_summary": "trading_date TEXT, account_id TEXT, currency TEXT, net_liquidation REAL, daily_pnl REAL, realized_pnl REAL, unrealized_pnl REAL, daily_return_pct REAL, top_profit_symbol TEXT, top_loss_symbol TEXT, pnl_sample_time_utc TEXT, data_age_sec REAL, stale INTEGER, report_path TEXT",
    "symbol_pnl_attribution": "trading_date TEXT, symbol TEXT, position_qty REAL, market_value REAL, daily_pnl REAL, realized_pnl REAL, unrealized_pnl REAL, contribution_pct_of_total_pnl REAL, contribution_pct_of_net_liquidation REAL, rank_by_profit INTEGER, rank_by_loss INTEGER, stale INTEGER, notes TEXT",
    "pool_transition_events": "timestamp TEXT, cycle_id TEXT, symbol TEXT, from_pool TEXT, to_pool TEXT, decision TEXT, blocked_reason TEXT, payload_json TEXT",
    "trade_pool_decisions": "timestamp TEXT, cycle_id TEXT, symbol TEXT, pool_layer TEXT, inclusion_reason TEXT, blocked_reason TEXT, market_session_state TEXT, expected_live_bid_ask INTEGER, bid_received INTEGER, ask_received INTEGER, quote_ready INTEGER, spread_ok INTEGER, event_risk_ok INTEGER, gap_risk_ok INTEGER, position_sizing_ok INTEGER, decision TEXT, execution_allowed INTEGER, order_submitted INTEGER, order_id TEXT, readback_status TEXT, payload_json TEXT",
    "market_session_events": "timestamp TEXT, cycle_id TEXT, session_state TEXT, expected_live_bid_ask INTEGER, blocked_reason TEXT, payload_json TEXT",
    "quote_readiness_events": "timestamp TEXT, cycle_id TEXT, symbol TEXT, quote_use_case TEXT, execution_allowed INTEGER, blocked_reason TEXT, payload_json TEXT",
    "order_readback_events": "timestamp TEXT, cycle_id TEXT, symbol TEXT, order_id TEXT, readback_ok INTEGER, blocked_reason TEXT, payload_json TEXT",
    "discovery_runs": "timestamp TEXT, discovery_run_id TEXT, status TEXT, sources_used INTEGER, candidates_count INTEGER, local_simulation_enabled INTEGER, ibkr_paper_order_submission INTEGER, live_trading_enabled INTEGER, payload_json TEXT",
    "discovery_source_status": "timestamp TEXT, discovery_run_id TEXT, source_name TEXT, source_type TEXT, enabled INTEGER, configured INTEGER, available INTEGER, used INTEGER, status TEXT, candidate_count INTEGER, error_message TEXT, report_path TEXT, payload_json TEXT",
    "discovery_candidates": "timestamp TEXT, discovery_run_id TEXT, symbol TEXT, source_name TEXT, source_type TEXT, inclusion_reason TEXT, blocked_reason TEXT, score REAL, payload_json TEXT",
    "ibkr_scanner_runs": "timestamp TEXT, discovery_run_id TEXT, status TEXT, tws_available INTEGER, scanner_codes_tested INTEGER, candidates_count INTEGER, paid_snapshot_used INTEGER, regulatory_snapshot_used INTEGER, payload_json TEXT",
    "ibkr_scanner_results": "timestamp_utc TEXT, discovery_run_id TEXT, source_type TEXT, scan_code TEXT, rank INTEGER, symbol TEXT, conId TEXT, exchange TEXT, primaryExchange TEXT, currency TEXT, secType TEXT, distance TEXT, benchmark TEXT, projection TEXT, raw_payload_ref TEXT, included_in_discovery INTEGER, blocked_reason TEXT, payload_json TEXT",
    "scanner_candidates": "timestamp TEXT, discovery_run_id TEXT, symbol TEXT, source_type TEXT, scan_code TEXT, rank INTEGER, score REAL, included_in_discovery INTEGER, blocked_reason TEXT, payload_json TEXT",
    "ibkr_news_provider_status": "timestamp TEXT, discovery_run_id TEXT, provider_code TEXT, provider_name TEXT, enabled INTEGER, available INTEGER, status TEXT, error_message TEXT, payload_json TEXT",
    "ibkr_news_interface_tests": "timestamp TEXT, discovery_run_id TEXT, interface_name TEXT, status TEXT, provider_code TEXT, symbol TEXT, conId TEXT, headline_count INTEGER, error_message TEXT, payload_json TEXT",
    "raw_news_events": "timestamp_utc TEXT, discovery_run_id TEXT, event_id TEXT, source TEXT, provider_code TEXT, symbol TEXT, headline TEXT, source_url_or_ref TEXT, raw_payload_ref TEXT, payload_json TEXT",
    "structured_news_events": "timestamp_utc TEXT, discovery_run_id TEXT, event_id TEXT, source TEXT, provider_code TEXT, symbol TEXT, conId TEXT, company_name TEXT, event_type TEXT, headline TEXT, summary TEXT, sentiment TEXT, urgency TEXT, confidence REAL, expected_impact TEXT, risk_level TEXT, action TEXT, reason TEXT, dedup_key TEXT, source_url_or_ref TEXT, raw_payload_ref TEXT, payload_json TEXT",
    "news_candidate_events": "timestamp TEXT, discovery_run_id TEXT, event_id TEXT, symbol TEXT, action TEXT, score_delta REAL, routed_to_pool INTEGER, blocked_reason TEXT, payload_json TEXT",
    "event_risk_events": "timestamp TEXT, discovery_run_id TEXT, event_id TEXT, symbol TEXT, risk_level TEXT, action TEXT, buy_blocked INTEGER, sell_review_required INTEGER, reason TEXT, payload_json TEXT",
    "fast_order_guidance_events": "timestamp_utc TEXT, discovery_run_id TEXT, guidance_id TEXT, symbol TEXT, source_event_id TEXT, source_type TEXT, urgency TEXT, confidence REAL, direction TEXT, recommended_intent_type TEXT, reason TEXT, required_gates TEXT, allowed_to_submit_order INTEGER, routed_to_order_intent_router INTEGER, blocked_reason TEXT, payload_json TEXT",
    "security_master": "timestamp TEXT, discovery_run_id TEXT, symbol TEXT, company_name TEXT, source_types TEXT, source_details TEXT, current_layer TEXT, first_seen_at TEXT, last_seen_at TEXT, included INTEGER, blocked_reason TEXT, payload_json TEXT",
    "pool_membership_history": "timestamp TEXT, discovery_run_id TEXT, symbol TEXT, pool_name TEXT, source TEXT, reason TEXT, score REAL, included INTEGER, excluded INTEGER, blocked_reason TEXT, last_updated_at TEXT, payload_json TEXT",
    "pool_source_events": "timestamp TEXT, discovery_run_id TEXT, symbol TEXT, source_type TEXT, source_name TEXT, reason TEXT, score REAL, payload_json TEXT",
    "candidate_scores": "timestamp TEXT, discovery_run_id TEXT, symbol TEXT, scanner_score REAL, news_score REAL, fast_guidance_score REAL, market_data_score REAL, volume_score REAL, gap_score REAL, liquidity_score REAL, strategy_score REAL, risk_score REAL, freshness_score REAL, final_candidate_score REAL, blocked_reason TEXT, payload_json TEXT",
    "candidate_score_components": "timestamp TEXT, discovery_run_id TEXT, symbol TEXT, component_name TEXT, component_value REAL, reason TEXT, payload_json TEXT",
    "buy_decisions": "event_id TEXT, timestamp TEXT, cycle_id TEXT, snapshot_id TEXT, state_version INTEGER, symbol TEXT, intent_id TEXT, decision TEXT, execution_allowed INTEGER, simulated_order_submitted INTEGER, ibkr_paper_order_submitted INTEGER, live_order_submitted INTEGER, order_submitted INTEGER, blocked_reason TEXT, payload_json TEXT",
    "sell_decisions": "event_id TEXT, timestamp TEXT, cycle_id TEXT, snapshot_id TEXT, state_version INTEGER, symbol TEXT, intent_id TEXT, intent_type TEXT, decision TEXT, execution_allowed INTEGER, simulated_order_submitted INTEGER, ibkr_paper_order_submitted INTEGER, live_order_submitted INTEGER, order_submitted INTEGER, blocked_reason TEXT, payload_json TEXT",
    "simulated_order_ledger": "timestamp_utc TEXT, simulation_run_id TEXT, simulated_order_id TEXT, intent_id TEXT, symbol TEXT, side TEXT, intent_type TEXT, order_type TEXT, quantity REAL, limit_price REAL, status TEXT, order_submitted INTEGER, ibkr_paper_order_submitted INTEGER, live_order_submitted INTEGER, payload_json TEXT",
    "simulated_execution_ledger": "timestamp_utc TEXT, simulation_run_id TEXT, simulated_execution_id TEXT, simulated_order_id TEXT, symbol TEXT, side TEXT, quantity REAL, fill_price REAL, fill_status TEXT, payload_json TEXT",
    "simulated_position_snapshots": "timestamp_utc TEXT, simulation_run_id TEXT, symbol TEXT, position_qty REAL, avg_cost REAL, market_price REAL, market_value REAL, unrealized_pnl REAL, payload_json TEXT",
    "simulated_pnl_snapshots": "timestamp_utc TEXT, simulation_run_id TEXT, account_id TEXT, currency TEXT, simulated_cash REAL, simulated_equity REAL, simulated_daily_pnl REAL, payload_json TEXT",
    "paper_execution_gate_events": "timestamp TEXT, cycle_id TEXT, paper_execution_enabled INTEGER, live_trading_enabled INTEGER, ibkr_paper_order_submission INTEGER, gate_status TEXT, blocked_reason TEXT, payload_json TEXT",
    "paper_order_readiness_events": "timestamp TEXT, cycle_id TEXT, readiness_key TEXT, ready INTEGER, blocked_reason TEXT, payload_json TEXT",
    "account_state_events": "event_id TEXT, timestamp_utc TEXT, state_version INTEGER, source_event_seq INTEGER, source_module TEXT, freshness_age_sec REAL, stale_flag INTEGER, payload_json TEXT",
    "position_state_events": "event_id TEXT, timestamp_utc TEXT, state_version INTEGER, source_event_seq INTEGER, source_module TEXT, symbol TEXT, freshness_age_sec REAL, stale_flag INTEGER, payload_json TEXT",
    "quote_state_events": "event_id TEXT, timestamp_utc TEXT, state_version INTEGER, source_event_seq INTEGER, source_module TEXT, symbol TEXT, bid REAL, ask REAL, last REAL, freshness_age_sec REAL, stale_flag INTEGER, payload_json TEXT",
    "pnl_state_events": "event_id TEXT, timestamp_utc TEXT, state_version INTEGER, source_event_seq INTEGER, source_module TEXT, freshness_age_sec REAL, stale_flag INTEGER, payload_json TEXT",
    "open_order_state_events": "event_id TEXT, timestamp_utc TEXT, state_version INTEGER, source_event_seq INTEGER, source_module TEXT, symbol TEXT, freshness_age_sec REAL, stale_flag INTEGER, payload_json TEXT",
    "execution_state_events": "event_id TEXT, timestamp_utc TEXT, state_version INTEGER, source_event_seq INTEGER, source_module TEXT, symbol TEXT, freshness_age_sec REAL, stale_flag INTEGER, payload_json TEXT",
    "commission_events": "event_id TEXT, timestamp_utc TEXT, cycle_id TEXT, snapshot_id TEXT, source_type TEXT, callback_name TEXT, req_id INTEGER, conId TEXT, symbol TEXT, commission REAL, currency TEXT, realized_pnl REAL, state_version INTEGER, payload_json TEXT",
    "ibkr_error_events": "event_id TEXT, timestamp_utc TEXT, source_type TEXT, callback_name TEXT, req_id INTEGER, error_code INTEGER, error_message TEXT, state_version INTEGER, payload_json TEXT",
    "callback_wiring_events": "event_id TEXT, timestamp_utc TEXT, source_type TEXT, callback_name TEXT, source_module TEXT, logical_bus TEXT, event_type_written TEXT, wired_to_realtime_bus INTEGER, payload_json TEXT",
    "subscription_state_events": "event_id TEXT, timestamp_utc TEXT, stream_name TEXT, callback_wired INTEGER, callback_registered INTEGER, subscription_requested INTEGER, subscription_active INTEGER, last_event_seen_at TEXT, last_event_source TEXT, freshness_status TEXT, waiting_reason TEXT, reconnect_count INTEGER, last_reconnect_at TEXT, payload_json TEXT",
    "bootstrap_state_events": "event_id TEXT, timestamp_utc TEXT, field_name TEXT, source_type TEXT, source_timestamp TEXT, current_age_sec REAL, stale_threshold_sec REAL, freshness_status TEXT, bus_status TEXT, payload_json TEXT",
    "timestamp_reconciliation_events": "event_id TEXT, timestamp_utc TEXT, field_name TEXT, symbol TEXT, incoming_source_type TEXT, incoming_source_timestamp TEXT, previous_source_type TEXT, previous_source_timestamp TEXT, accepted INTEGER, reason TEXT, state_version INTEGER, payload_json TEXT",
    "state_versions": "state_version INTEGER, timestamp_utc TEXT, state_key TEXT, source_event_seq INTEGER, source_module TEXT, stale_flag INTEGER, payload_json TEXT",
    "cycle_snapshots": "cycle_id TEXT, snapshot_id TEXT, timestamp_utc TEXT, created_at TEXT, trigger_event_id TEXT, account_state_ref TEXT, position_state_ref TEXT, quote_state_ref TEXT, pnl_state_ref TEXT, open_order_state_ref TEXT, execution_state_ref TEXT, market_data_ref TEXT, market_session_ref TEXT, pool_state_ref TEXT, news_state_ref TEXT, scanner_state_ref TEXT, trigger_state_ref TEXT, risk_state_ref TEXT, state_version_min INTEGER, state_version_max INTEGER, immutable INTEGER, payload_json TEXT",
    "order_conflict_events": "event_id TEXT, timestamp_utc TEXT, cycle_id TEXT, snapshot_id TEXT, symbol TEXT, conflict_type TEXT, buy_intent_id TEXT, sell_intent_id TEXT, decision TEXT, blocked_reason TEXT, payload_json TEXT",
    "router_decisions": "event_id TEXT, timestamp_utc TEXT, cycle_id TEXT, snapshot_id TEXT, symbol TEXT, decision TEXT, execution_allowed INTEGER, blocked_reason TEXT, payload_json TEXT",
    "event_store": "event_id TEXT, timestamp_utc TEXT, cycle_id TEXT, snapshot_id TEXT, source_module TEXT, event_type TEXT, symbol TEXT, state_version INTEGER, payload_json TEXT, report_path TEXT",
    "position_lifecycle_events": "event_id TEXT, timestamp_utc TEXT, lifecycle_id TEXT, symbol TEXT, account_id TEXT, mode TEXT, from_state TEXT, to_state TEXT, intent_id TEXT, order_id TEXT, pnl_ref TEXT, blocked_reason TEXT, payload_json TEXT",
    "position_lifecycle_state": "lifecycle_id TEXT, symbol TEXT, account_id TEXT, mode TEXT, current_state TEXT, candidate_id TEXT, signal_id TEXT, buy_intent_id TEXT, buy_order_id TEXT, position_id TEXT, protection_required INTEGER, protection_plan_status TEXT, protection_intent_id TEXT, sell_intent_id TEXT, pnl_ref TEXT, created_at TEXT, updated_at TEXT, blocked_reason TEXT, payload_json TEXT",
    "strategy_signals": "signal_id TEXT, timestamp_utc TEXT, cycle_id TEXT, snapshot_id TEXT, symbol TEXT, signal_type TEXT, direction TEXT, source_module TEXT, source_reason TEXT, confidence REAL, urgency TEXT, score REAL, linked_pool_ref TEXT, linked_news_ref TEXT, linked_scanner_ref TEXT, linked_position_ref TEXT, linked_pnl_ref TEXT, blocked_reason TEXT, payload_json TEXT",
}

GENERIC_DECISION_COLUMNS = {
    "timestamp",
    "cycle_id",
    "module",
    "symbol",
    "decision_type",
    "input_state_ref",
    "market_session_state",
    "quote_state_ref",
    "account_state_ref",
    "risk_state_ref",
    "decision",
    "execution_allowed",
    "order_submitted",
    "order_id",
    "blocked_reason",
    "report_path",
}


def ensure_paper_automation_tables(db_path: Path = DB_PATH) -> None:
    with sqlite3.connect(db_path) as con:
        for table, columns in PAPER_AUTOMATION_TABLES.items():
            con.execute(f"CREATE TABLE IF NOT EXISTS {table} ({columns})")
            existing = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
            for definition in _column_definitions(columns):
                name = definition.split()[0]
                if name not in existing:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def insert_event(table: str, values: Mapping[str, Any], *, db_path: Path = DB_PATH) -> None:
    ensure_paper_automation_tables(db_path)
    if table not in PAPER_AUTOMATION_TABLES:
        raise ValueError(f"unknown paper automation table: {table}")
    columns = [part.strip().split()[0] for part in PAPER_AUTOMATION_TABLES[table].split(",")]
    row = {column: values.get(column) for column in columns}
    if "timestamp" in row and not row["timestamp"]:
        row["timestamp"] = utc_now()
    if "payload_json" in row and row["payload_json"] is None:
        row["payload_json"] = json.dumps(dict(values), sort_keys=True)
    placeholders = ", ".join("?" for _ in columns)
    with sqlite3.connect(db_path) as con:
        con.execute(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
            [row.get(column) for column in columns],
        )


def generic_decision_event(
    *,
    cycle_id: str,
    module: str,
    symbol: str = "",
    decision_type: str,
    input_state_ref: str = "",
    market_session_state: str = "",
    quote_state_ref: str = "",
    account_state_ref: str = "",
    risk_state_ref: str = "",
    decision: str,
    execution_allowed: bool,
    order_submitted: bool = False,
    order_id: str = "",
    blocked_reason: str = "",
    report_path: str = "",
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "timestamp": utc_now(),
        "cycle_id": cycle_id,
        "module": module,
        "symbol": symbol,
        "decision_type": decision_type,
        "input_state_ref": input_state_ref,
        "market_session_state": market_session_state,
        "quote_state_ref": quote_state_ref,
        "account_state_ref": account_state_ref,
        "risk_state_ref": risk_state_ref,
        "decision": decision,
        "execution_allowed": execution_allowed,
        "order_submitted": order_submitted,
        "order_id": order_id,
        "blocked_reason": blocked_reason,
        "report_path": report_path,
    }
    if extra:
        payload.update(dict(extra))
    return payload


def sqlite_table_summary(db_path: Path = DB_PATH) -> dict[str, Any]:
    ensure_paper_automation_tables(db_path)
    summary: dict[str, Any] = {}
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        for table in PAPER_AUTOMATION_TABLES:
            count = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            latest = con.execute(f"SELECT * FROM {table} ORDER BY rowid DESC LIMIT 1").fetchone()
            columns = [row["name"] for row in con.execute(f"PRAGMA table_info({table})")]
            summary[table] = {
                "table_exists": True,
                "row_count": count,
                "columns": columns,
                "has_generic_decision_fields": sorted(GENERIC_DECISION_COLUMNS & set(columns)),
                "latest_row": dict(latest) if latest else None,
            }
    return summary


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _column_definitions(columns: str) -> list[str]:
    return [item.strip() for item in columns.split(",") if item.strip()]
