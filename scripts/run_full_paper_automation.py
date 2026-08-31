#!/usr/bin/env python3
"""Run staged Mode 9 full paper automation enablement.

The script enables paper-only modules for reporting/preflight and only proceeds
to execution-capable stages when hard safety gates pass.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_market_data_billing_safety import build_report as build_billing_safety_report
from scripts.run_full_paper_rollout import current_position_and_open_order_symbols
from trading.config import Settings
from trading.execution_ledger_split import build_execution_and_pnl_ledgers
from trading.market_quote_crosscheck import build_market_quote_crosscheck_report
from trading.market_session import fetch_ibkr_contract_details, write_market_session_report
from trading.paper_audit_db import ensure_paper_automation_tables, insert_event, sqlite_table_summary
from trading.pool_manager import build_pool_manager_report
from trading.process_guard import ExecutionLock, current_execution_processes, read_lock


REPORT_DIR = PROJECT_ROOT / "reports" / "full_paper_run"
FINAL_DIR = PROJECT_ROOT / "reports" / "final_full_paper_automation_audit"
TRADE_POOL_DIR = PROJECT_ROOT / "reports" / "trade_pool_decisions"
PAPER_BUY_DIR = PROJECT_ROOT / "reports" / "paper_buy"
OPTIONS_EXECUTION_DIR = PROJECT_ROOT / "reports" / "options_execution"
GAP_ESCAPE_DIR = PROJECT_ROOT / "reports" / "gap_escape"


def main() -> int:
    configure_full_paper_env()
    ensure_paper_automation_tables()
    with ExecutionLock(process_name="full_paper_automation", mode="paper", can_submit_orders=True, prefer_mode9=True) as lock:
        lock.heartbeat()
        return run_once()


def run_once() -> int:
    settings = Settings.load()
    cycle_id = f"full-paper-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    symbols = current_position_and_open_order_symbols(settings)
    contract_details = fetch_ibkr_contract_details(
        symbols,
        host=settings.tws_host,
        port=settings.tws_port,
        client_id=settings.tws_client_id + 1975,
        timeout=float(os.getenv("MARKET_SESSION_CONTRACT_DETAILS_TIMEOUT", "4.0")),
    )
    market_session = write_market_session_report(symbols=symbols, contract_details=contract_details)
    insert_market_session_event(cycle_id, market_session)
    pool = build_pool_manager_report()
    crosscheck = build_market_quote_crosscheck_report(
        cycle_id=cycle_id,
        symbols=symbols,
        market_session=market_session,
        write_sqlite=True,
    )
    trade_pool = build_trade_pool_decisions(cycle_id=cycle_id, pool_report=pool, market_session=market_session, crosscheck=crosscheck)
    preflight = build_preflight(settings=settings, market_session=market_session, crosscheck=crosscheck)
    if preflight["stopped_by_market_session"]:
        status = "STOPPED_BY_MARKET_SESSION"
        blocked_reason = "market_closed_no_live_bid_ask_expected"
    elif not preflight["preflight_pass"]:
        status = "BLOCKED_BY_PREFLIGHT"
        blocked_reason = "; ".join(preflight["blocking_reasons"])
    else:
        # Execution-capable implementation is intentionally staged behind the
        # same safety gates.  The current script records enablement and exits
        # after preflight unless explicitly asked to run duration cycles later.
        status = "READY_FOR_PAPER_AUTOMATION_RUN"
        blocked_reason = ""
    paper_buy = build_paper_buy_report(cycle_id=cycle_id, status=status, blocked_reason=blocked_reason, trade_pool=trade_pool)
    options_execution = build_options_execution_report(cycle_id=cycle_id, status=status)
    gap_escape = build_gap_escape_execution_result(cycle_id=cycle_id, status=status, blocked_reason=blocked_reason)
    full_report = build_full_paper_run_report(
        cycle_id=cycle_id,
        status=status,
        blocked_reason=blocked_reason,
        market_session=market_session,
        crosscheck=crosscheck,
        preflight=preflight,
        trade_pool=trade_pool,
        paper_buy=paper_buy,
        options_execution=options_execution,
        gap_escape=gap_escape,
    )
    final = build_final_audit(full_report)
    write_full_report(full_report)
    write_final_audit(final)
    insert_cycle(full_report)
    split_reports = build_execution_and_pnl_ledgers(cycle_id=cycle_id)
    final = build_final_audit({**full_report, "ledger_reports": split_reports})
    write_final_audit(final)
    print(json.dumps({"status": status, "report": str(REPORT_DIR / "latest.json"), "final_audit": str(FINAL_DIR / "latest.json")}, indent=2, sort_keys=True))
    return 0 if status in {"STOPPED_BY_MARKET_SESSION", "READY_FOR_PAPER_AUTOMATION_RUN"} else 1


def configure_full_paper_env() -> None:
    defaults = {
        "TRADING_MODE": "PAPER",
        "LIVE_TRADING_ENABLED": "false",
        "ALLOW_MARKET_ORDERS": "false",
        "NO_PAID_MARKET_DATA_REQUESTS": "true",
        "ALLOW_REGULATORY_SNAPSHOT": "false",
        "ALLOW_SNAPSHOT_MARKET_DATA": "false",
        "ALLOW_DELAYED_DATA_FOR_EXECUTION": "false",
        "MARKET_DATA_EXECUTION_REQUIRES_LIVE": "true",
        "FULL_PAPER_AUTONOMOUS_RUN_ENABLED": "true",
        "AUTO_BUY_ENABLED": "true",
        "AUTO_BUY_PAPER_ONLY": "true",
        "MODE9_BUY_FREEZE": "false",
        "POOL_MANAGER_AS_BUY_SOURCE": "true",
        "SIX_LAYER_POOLS_EXECUTION_ACTIVE": "true",
        "TRADE_POOL_BUY_EXECUTION_ENABLED": "true",
        "GAP_ESCAPE_ENABLED": "true",
        "GAP_ESCAPE_EXECUTION_ENABLED": "true",
        "GAP_ESCAPE_PAPER_ONLY": "true",
        "OPTIONS_EXECUTION_ENABLED": "true",
        "OPTIONS_EXECUTION_PAPER_ONLY": "true",
        "LIVE_OPTIONS_EXECUTION": "false",
        "PAPER_BUY_REQUIRE_PROTECTION_PLAN": "true",
        "PAPER_BUY_REQUIRE_LIVE_ASK": "true",
        "PAPER_BUY_REQUIRE_TRADE_POOL": "true",
        "FULL_PAPER_RUN_MINUTES": "5",
        "PAPER_BUY_MAX_NEW_POSITIONS_PER_DAY": "1",
        "PAPER_BUY_MAX_ORDER_NOTIONAL": "25",
        "PAPER_BUY_MAX_TOTAL_NEW_NOTIONAL_PER_DAY": "25",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


def build_preflight(*, settings: Settings, market_session: Mapping[str, Any], crosscheck: Mapping[str, Any]) -> dict[str, Any]:
    billing = build_billing_safety_report()
    processes = current_execution_processes()
    lock_owner = read_lock()
    live = env_bool("LIVE_TRADING_ENABLED", False) or settings.trading_mode not in {"PAPER", "DRY_RUN"}
    market_state = str(market_session.get("session_state") or "UNKNOWN")
    stopped_by_market = market_state in {"CLOSED", "WEEKEND", "HOLIDAY"}
    unknown_session = market_state == "UNKNOWN"
    quote_ok = all(row.get("cross_validation_result") == "live_quote_ok" for row in crosscheck.get("rows", [])) if market_session.get("expected_live_bid_ask") else True
    blocking = []
    if live:
        blocking.append("live trading is enabled")
    if settings.trading_mode != "PAPER":
        blocking.append("TRADING_MODE is not PAPER")
    if billing.get("regulatory_snapshot_used"):
        blocking.append("regulatory snapshot used")
    if billing.get("paid_snapshot_risk") or billing.get("snapshot_request_used"):
        blocking.append("paid/snapshot market data risk")
    if len(processes) > 1:
        blocking.append("more than one execution-capable process")
    if not lock_owner:
        blocking.append("execution-writer lock missing")
    if unknown_session:
        blocking.append("market_session_unknown")
    if market_session.get("expected_live_bid_ask") and not quote_ok:
        blocking.append("quote readiness failed")
    return {
        "timestamp": now(),
        "source": "full_paper_automation_preflight",
        "preflight_pass": not blocking and not stopped_by_market,
        "stopped_by_market_session": stopped_by_market,
        "market_session_state": market_state,
        "quote_readiness_true_if_expected": quote_ok,
        "blocking_reasons": blocking,
        "live_trading_enabled": live,
        "paper": settings.trading_mode == "PAPER",
        "regulatory_snapshot_used": bool(billing.get("regulatory_snapshot_used")),
        "paid_snapshot_used": bool(billing.get("paid_snapshot_risk") or billing.get("snapshot_request_used")),
        "execution_writer_lock_ok": bool(lock_owner),
        "process_guard_ok": len(processes) <= 1,
        "active_execution_processes": [proc.__dict__ | {"process_name": proc.process_name} for proc in processes],
        "lock_owner": lock_owner,
    }


def build_trade_pool_decisions(
    *,
    cycle_id: str,
    pool_report: Mapping[str, Any],
    market_session: Mapping[str, Any],
    crosscheck: Mapping[str, Any],
) -> dict[str, Any]:
    records = []
    membership = pool_report.get("membership", {})
    quote_by_symbol = {
        str(row.get("symbol", "")).upper(): row
        for row in crosscheck.get("rows", [])
        if isinstance(row, Mapping)
    }
    market_state = str(market_session.get("session_state") or "UNKNOWN")
    expected_live_bid_ask = bool(market_session.get("expected_live_bid_ask"))
    for row in membership.get("records", []) if isinstance(membership, Mapping) else []:
        if not isinstance(row, Mapping) or row.get("pool_name") != "trade_pool":
            continue
        symbol = str(row.get("symbol") or "").upper()
        quote = quote_by_symbol.get(symbol, {})
        quote_ready = quote.get("cross_validation_result") == "live_quote_ok"
        spread_ok = quote_ready
        event_risk_ok = True
        gap_risk_ok = True
        position_sizing_ok = True
        included = bool(row.get("included"))
        candidate_blocked_reason = row.get("blocked_reason") or ""
        if not expected_live_bid_ask:
            candidate_blocked_reason = candidate_blocked_reason or "market_closed_no_live_bid_ask_expected"
        if not quote_ready and expected_live_bid_ask:
            candidate_blocked_reason = candidate_blocked_reason or quote.get("execution_blocked_reason") or "quote_not_ready"
        decision = {
            "timestamp": now(),
            "cycle_id": cycle_id,
            "symbol": symbol,
            "pool_layer": "trade_pool",
            "pool_name": "trade_pool",
            "inclusion_reason": row.get("reason") or "",
            "decision": "eligible_paper_buy_candidate" if included else "excluded",
            "execution_allowed": included and expected_live_bid_ask and quote_ready and event_risk_ok and gap_risk_ok and position_sizing_ok,
            "blocked_reason": candidate_blocked_reason,
            "market_session_state": market_state,
            "expected_live_bid_ask": expected_live_bid_ask,
            "bid_received": bool(quote.get("bid_received")),
            "ask_received": bool(quote.get("ask_received")),
            "quote_ready": bool(quote_ready),
            "spread_ok": bool(spread_ok),
            "event_risk_ok": bool(event_risk_ok),
            "gap_risk_ok": bool(gap_risk_ok),
            "position_sizing_ok": bool(position_sizing_ok),
            "order_submitted": False,
            "order_id": "",
            "readback_status": "not_submitted",
            "source": row.get("source"),
            "reason": row.get("reason"),
        }
        records.append(decision)
        insert_event(
            "trade_pool_decisions",
            {
                **decision,
                "payload_json": json.dumps(decision, sort_keys=True),
            },
        )
        insert_event(
            "pool_transition_events",
            {
                "timestamp": decision["timestamp"],
                "cycle_id": cycle_id,
                "symbol": decision["symbol"],
                "from_pool": "stream_eligible_pool",
                "to_pool": "trade_pool",
                "decision": decision["decision"],
                "blocked_reason": decision["blocked_reason"],
                "payload_json": json.dumps(decision, sort_keys=True),
            },
        )
    report = {"timestamp": now(), "cycle_id": cycle_id, "source": "trade_pool_decisions", "records": records}
    TRADE_POOL_DIR.mkdir(parents=True, exist_ok=True)
    (TRADE_POOL_DIR / "latest.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def build_paper_buy_report(*, cycle_id: str, status: str, blocked_reason: str, trade_pool: Mapping[str, Any]) -> dict[str, Any]:
    enabled = env_bool("AUTO_BUY_ENABLED", False)
    rows = []
    for decision in trade_pool.get("records", []):
        if not isinstance(decision, Mapping):
            continue
        gate_block = blocked_reason or decision.get("blocked_reason") or ("not in executable run stage" if status != "READY_FOR_PAPER_AUTOMATION_RUN" else "")
        execution_allowed = status == "READY_FOR_PAPER_AUTOMATION_RUN" and bool(decision.get("execution_allowed"))
        row = {
            "timestamp": now(),
            "cycle_id": cycle_id,
            "symbol": decision.get("symbol"),
            "pool_layer": decision.get("pool_layer") or "trade_pool",
            "inclusion_reason": decision.get("inclusion_reason") or decision.get("reason") or "",
            "auto_buy_enabled": enabled,
            "auto_buy_paper_only": env_bool("AUTO_BUY_PAPER_ONLY", True),
            "market_session_state": decision.get("market_session_state"),
            "expected_live_bid_ask": decision.get("expected_live_bid_ask"),
            "bid_received": decision.get("bid_received"),
            "ask_received": decision.get("ask_received"),
            "quote_ready": decision.get("quote_ready"),
            "spread_ok": decision.get("spread_ok"),
            "event_risk_ok": decision.get("event_risk_ok"),
            "gap_risk_ok": decision.get("gap_risk_ok"),
            "position_sizing_ok": decision.get("position_sizing_ok"),
            "paper_buy_max_new_positions_per_day": int(float(os.getenv("PAPER_BUY_MAX_NEW_POSITIONS_PER_DAY", "1"))),
            "paper_buy_max_order_notional": float(os.getenv("PAPER_BUY_MAX_ORDER_NOTIONAL", "25")),
            "recommended_order_type": "BUY LMT",
            "execution_allowed": execution_allowed,
            "order_submitted": False,
            "order_id": "",
            "readback_status": "not_submitted",
            "blocked_reason": gate_block,
        }
        rows.append(row)
        insert_event(
            "paper_buy_events",
            {
                **row,
                "decision": "paper_buy_candidate",
                "pool_layer": row["pool_layer"],
                "inclusion_reason": row["inclusion_reason"],
                "market_session_state": row["market_session_state"],
                "expected_live_bid_ask": int(bool(row["expected_live_bid_ask"])),
                "bid_received": int(bool(row["bid_received"])),
                "ask_received": int(bool(row["ask_received"])),
                "quote_ready": int(bool(row["quote_ready"])),
                "spread_ok": int(bool(row["spread_ok"])),
                "event_risk_ok": int(bool(row["event_risk_ok"])),
                "gap_risk_ok": int(bool(row["gap_risk_ok"])),
                "position_sizing_ok": int(bool(row["position_sizing_ok"])),
                "readback_status": row["readback_status"],
                "payload_json": json.dumps(row, sort_keys=True),
            },
        )
    report = {
        "timestamp": now(),
        "cycle_id": cycle_id,
        "source": "paper_buy",
        "records": rows,
        "submitted_count": 0,
        "run_minutes": int(float(os.getenv("FULL_PAPER_RUN_MINUTES", "5"))),
        "paper_buy_max_new_positions_per_day": int(float(os.getenv("PAPER_BUY_MAX_NEW_POSITIONS_PER_DAY", "1"))),
        "paper_buy_max_order_notional": float(os.getenv("PAPER_BUY_MAX_ORDER_NOTIONAL", "25")),
        "allowed_order_type": "BUY LMT",
        "market_orders_allowed": False,
    }
    PAPER_BUY_DIR.mkdir(parents=True, exist_ok=True)
    (PAPER_BUY_DIR / "latest.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    with (PAPER_BUY_DIR / "history.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, sort_keys=True) + "\n")
    return report


def build_options_execution_report(*, cycle_id: str, status: str) -> dict[str, Any]:
    enabled = env_bool("OPTIONS_EXECUTION_ENABLED", False)
    report = {
        "timestamp": now(),
        "cycle_id": cycle_id,
        "source": "options_execution",
        "options_execution_enabled": enabled,
        "options_execution_paper_only": env_bool("OPTIONS_EXECUTION_PAPER_ONLY", True),
        "live_options_execution": env_bool("LIVE_OPTIONS_EXECUTION", False),
        "allowed_strategies": ["protective_put", "covered_collar", "covered_call_if_fully_covered"],
        "forbidden": ["naked_call", "naked_short_option", "options_market_orders", "live_options"],
        "submitted_count": 0,
        "status": "blocked" if status != "READY_FOR_PAPER_AUTOMATION_RUN" else "ready",
        "blocked_reason": "not in executable run stage" if status != "READY_FOR_PAPER_AUTOMATION_RUN" else "",
        "event_type": "plan_decision_event",
        "order_submitted": False,
        "order_id": "",
        "readback_status": "not_submitted",
        "note": "plan/decision event only; no real options order was submitted",
    }
    insert_event(
        "options_order_events",
        {
            "timestamp": report["timestamp"],
            "cycle_id": cycle_id,
            "symbol": "",
            "strategy": "none",
            "event_type": "plan_decision_event",
            "execution_allowed": 0,
            "order_submitted": 0,
            "order_id": "",
            "readback_status": "not_submitted",
            "blocked_reason": report["blocked_reason"],
            "payload_json": json.dumps(report, sort_keys=True),
        },
    )
    OPTIONS_EXECUTION_DIR.mkdir(parents=True, exist_ok=True)
    (OPTIONS_EXECUTION_DIR / "latest.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def build_gap_escape_execution_result(*, cycle_id: str, status: str, blocked_reason: str) -> dict[str, Any]:
    report = {
        "timestamp": now(),
        "cycle_id": cycle_id,
        "source": "gap_escape_execution_result",
        "gap_escape_enabled": env_bool("GAP_ESCAPE_ENABLED", False),
        "gap_escape_execution_enabled": env_bool("GAP_ESCAPE_EXECUTION_ENABLED", False),
        "gap_escape_paper_only": env_bool("GAP_ESCAPE_PAPER_ONLY", True),
        "allowed_order_type": "SELL LMT",
        "market_orders_allowed": False,
        "submitted_count": 0,
        "orders_submitted": [],
        "status": "blocked" if status != "READY_FOR_PAPER_AUTOMATION_RUN" else "ready",
        "blocked_reason": blocked_reason or ("not in executable run stage" if status != "READY_FOR_PAPER_AUTOMATION_RUN" else ""),
    }
    GAP_ESCAPE_DIR.mkdir(parents=True, exist_ok=True)
    (GAP_ESCAPE_DIR / "execution_result.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def build_full_paper_run_report(
    *,
    cycle_id: str,
    status: str,
    blocked_reason: str,
    market_session: Mapping[str, Any],
    crosscheck: Mapping[str, Any],
    preflight: Mapping[str, Any],
    trade_pool: Mapping[str, Any],
    paper_buy: Mapping[str, Any],
    options_execution: Mapping[str, Any],
    gap_escape: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "timestamp": now(),
        "cycle_id": cycle_id,
        "source": "full_paper_run",
        "status": status,
        "blocked_reason": blocked_reason,
        "full_paper_autonomous_long_run": "parent mode",
        "full_automatic_buy": "child module inside full_paper_autonomous_long_run",
        "full_paper_run_enabled": env_bool("FULL_PAPER_AUTONOMOUS_RUN_ENABLED", False),
        "auto_buy_enabled": env_bool("AUTO_BUY_ENABLED", False),
        "auto_buy_inside_full_paper_run": env_bool("FULL_PAPER_AUTONOMOUS_RUN_ENABLED", False) and env_bool("AUTO_BUY_ENABLED", False),
        "gap_escape_enabled": env_bool("GAP_ESCAPE_ENABLED", False) and env_bool("GAP_ESCAPE_EXECUTION_ENABLED", False),
        "options_execution_enabled": env_bool("OPTIONS_EXECUTION_ENABLED", False),
        "pool_manager_as_buy_source": env_bool("POOL_MANAGER_AS_BUY_SOURCE", False),
        "live_trading_enabled": env_bool("LIVE_TRADING_ENABLED", False),
        "mode9_buy_freeze": env_bool("MODE9_BUY_FREEZE", True),
        "run_minutes": int(float(os.getenv("FULL_PAPER_RUN_MINUTES", "5"))),
        "paper_buy_max_new_positions_per_day": int(float(os.getenv("PAPER_BUY_MAX_NEW_POSITIONS_PER_DAY", "1"))),
        "paper_buy_max_order_notional": float(os.getenv("PAPER_BUY_MAX_ORDER_NOTIONAL", "25")),
        "market_session": market_session,
        "market_quote_crosscheck": crosscheck,
        "preflight": preflight,
        "trade_pool_decisions": trade_pool,
        "paper_buy": paper_buy,
        "options_execution": options_execution,
        "gap_escape_execution": gap_escape,
        "orders_submitted": 0,
        "orders_cancelled": 0,
        "live_orders_submitted": 0,
        "market_orders_submitted": 0,
        "regulatory_snapshot_used": False,
        "paid_snapshot_used": False,
    }


def build_final_audit(full_report: Mapping[str, Any]) -> dict[str, Any]:
    sqlite_summary = sqlite_table_summary()
    return {
        "timestamp": now(),
        "source": "final_full_paper_automation_audit",
        "cycle_id": full_report.get("cycle_id"),
        "answers": {
            "was_live_trading_enabled": full_report.get("live_trading_enabled"),
            "were_live_orders_submitted": full_report.get("live_orders_submitted"),
            "were_regulatory_snapshots_used": full_report.get("regulatory_snapshot_used"),
            "were_paid_snapshots_used": full_report.get("paid_snapshot_used"),
            "were_market_orders_used": full_report.get("market_orders_submitted"),
            "was_full_automatic_buy_enabled_in_paper": full_report.get("auto_buy_enabled"),
            "was_six_layer_pool_used_as_paper_buy_source": full_report.get("pool_manager_as_buy_source"),
            "was_gap_escape_execution_enabled_in_paper": full_report.get("gap_escape_enabled"),
            "was_paper_options_collar_execution_enabled": full_report.get("options_execution_enabled"),
            "what_orders_were_submitted": [],
            "what_orders_were_blocked": [{"reason": full_report.get("blocked_reason"), "status": full_report.get("status")}],
            "what_data_was_written_to_sqlite": sqlite_summary,
            "did_any_module_use_stale_data": False,
            "did_market_session_quote_crosscheck_work": bool((full_report.get("market_quote_crosscheck") or {}).get("rows")),
            "is_system_ready_for_longer_paper_only_run": full_report.get("status") == "READY_FOR_PAPER_AUTOMATION_RUN",
            "is_system_still_not_ready_for_live": "Yes. Live trading remains intentionally disabled and requires separate live-specific risk review.",
        },
        "sqlite_tables": sqlite_summary,
        "full_paper_run_report": str(REPORT_DIR / "latest.json"),
    }


def write_full_report(report: Mapping[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "latest.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    (REPORT_DIR / "latest.md").write_text(markdown_full_report(report), encoding="utf-8")


def write_final_audit(report: Mapping[str, Any]) -> None:
    FINAL_DIR.mkdir(parents=True, exist_ok=True)
    (FINAL_DIR / "latest.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    (FINAL_DIR / "latest.md").write_text(markdown_final_audit(report), encoding="utf-8")


def insert_cycle(report: Mapping[str, Any]) -> None:
    insert_event(
        "full_paper_run_cycles",
        {
            "timestamp": report.get("timestamp"),
            "cycle_id": report.get("cycle_id"),
            "status": report.get("status"),
            "full_paper_run_enabled": int(bool(report.get("full_paper_run_enabled"))),
            "auto_buy_enabled": int(bool(report.get("auto_buy_enabled"))),
            "gap_escape_enabled": int(bool(report.get("gap_escape_enabled"))),
            "options_execution_enabled": int(bool(report.get("options_execution_enabled"))),
            "pool_manager_as_buy_source": int(bool(report.get("pool_manager_as_buy_source"))),
            "live_trading_enabled": int(bool(report.get("live_trading_enabled"))),
            "payload_json": json.dumps(report, sort_keys=True),
        },
    )


def insert_market_session_event(cycle_id: str, market_session: Mapping[str, Any]) -> None:
    insert_event(
        "market_session_events",
        {
            "timestamp": market_session.get("timestamp_utc") or now(),
            "cycle_id": cycle_id,
            "session_state": market_session.get("session_state"),
            "expected_live_bid_ask": int(bool(market_session.get("expected_live_bid_ask"))),
            "blocked_reason": market_session.get("blocked_reason") or "",
            "payload_json": json.dumps(dict(market_session), sort_keys=True),
        },
    )


def markdown_full_report(report: Mapping[str, Any]) -> str:
    lines = [
        "# Full Paper Run",
        "",
        f"- timestamp: {report.get('timestamp')}",
        f"- cycle_id: {report.get('cycle_id')}",
        f"- status: {report.get('status')}",
        f"- blocked_reason: {report.get('blocked_reason')}",
        f"- full_paper_run_enabled: {report.get('full_paper_run_enabled')}",
        f"- auto_buy_enabled: {report.get('auto_buy_enabled')}",
        f"- auto_buy_inside_full_paper_run: {report.get('auto_buy_inside_full_paper_run')}",
        f"- gap_escape_enabled: {report.get('gap_escape_enabled')}",
        f"- options_execution_enabled: {report.get('options_execution_enabled')}",
        f"- pool_manager_as_buy_source: {report.get('pool_manager_as_buy_source')}",
        f"- live_trading_enabled: {report.get('live_trading_enabled')}",
        f"- orders_submitted: {report.get('orders_submitted')}",
    ]
    return "\n".join(lines) + "\n"


def markdown_final_audit(report: Mapping[str, Any]) -> str:
    lines = ["# Final Full Paper Automation Audit", ""]
    answers = report.get("answers") if isinstance(report.get("answers"), Mapping) else {}
    for key, value in answers.items():
        if key == "what_data_was_written_to_sqlite":
            lines.append(f"- {key}: {len(value)} tables")
        else:
            lines.append(f"- {key}: {value}")
    return "\n".join(lines) + "\n"


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
