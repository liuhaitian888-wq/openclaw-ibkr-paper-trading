#!/usr/bin/env python3
"""Run gated PAPER-only Mode 9 rollout stages."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_account_reports import main as build_account_reports_main
from scripts.build_market_data_billing_safety import build_report as build_billing_safety_report
from scripts.list_tws_orders import read_tws_orders
from scripts.record_account_pnl import main as record_account_pnl_main
from trading.account_state_manager import (
    build_account_state,
    build_force_refresh_dry_run,
    overlay_streaming_quotes,
    refresh_streaming_quote_diagnostics,
)
from trading.config import Settings
from trading.market_session import fetch_ibkr_contract_details, write_market_session_report
from trading.position_guard import build_position_guard_report
from trading.position_protection import build_repair_preview_report, load_repair_config, load_stop_config
from trading.process_guard import ExecutionLock, current_execution_processes, read_lock
from trading.tws_paper import TwsPaperBroker


REPORT_DIR = PROJECT_ROOT / "reports" / "full_paper_rollout"
POSITION_PROTECTION_DIR = PROJECT_ROOT / "reports" / "position_protection"
ACTIVE_ORDER_STATUSES = {"Submitted", "PreSubmitted", "Accepted", "ApiPending", "PendingSubmit"}


def main() -> int:
    configure_safe_env()
    max_stage = int(os.getenv("FULL_PAPER_ROLLOUT_MAX_STAGE", "2"))
    settings = Settings.load()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    stages: list[dict[str, Any]] = []
    with ExecutionLock(
        process_name="mode9_autonomous_agent",
        mode="paper",
        can_submit_orders=True,
        prefer_mode9=True,
    ) as lock:
        lock.heartbeat()
        stage0 = stage0_preflight(settings)
        stages.append(stage0)
        if not stage0["stage_status"] == "PASS" or max_stage < 1:
            write_summary(stages)
            return 0 if stage0["stage_status"] == "PASS" else 1

        lock.heartbeat()
        stage1 = stage1_readiness(settings)
        stages.append(stage1)
        if stage1["stage_status"] != "PASS" or max_stage < 2:
            write_summary(stages)
            return 0 if all(stage["stage_status"] == "PASS" for stage in stages) else 1

        lock.heartbeat()
        stage2 = stage2_protective_repair(settings)
        stages.append(stage2)
        write_summary(stages)
        return 0 if all(stage["stage_status"] == "PASS" for stage in stages) else 1


def configure_safe_env() -> None:
    defaults = {
        "TRADING_MODE": "PAPER",
        "LIVE_TRADING_ENABLED": "false",
        "MODE9_BUY_FREEZE": "true",
        "ALLOW_OPTIONS_EXECUTION": "false",
        "ALLOW_MARKET_ORDERS": "false",
        "NO_PAID_MARKET_DATA_REQUESTS": "true",
        "ALLOW_REGULATORY_SNAPSHOT": "false",
        "ALLOW_SNAPSHOT_MARKET_DATA": "false",
        "ALLOW_DELAYED_DATA_FOR_EXECUTION": "false",
        "MARKET_DATA_EXECUTION_REQUIRES_LIVE": "true",
        "POSITION_PROTECTION_REPAIR_ENABLED": "false",
        "POSITION_PROTECTION_REPAIR_MODE": "run",
        "POSITION_PROTECTION_ORDER_TYPE": "STP_LMT",
        "POSITION_PROTECTION_OUTSIDE_RTH_REQUIRED": "true",
        "POSITION_PROTECTION_AUTO_CONVERT_STP_TO_STP_LMT": "false",
        "GAP_ESCAPE_EXECUTION_ENABLED": "false",
        "TRADE_POOL_BUY_EXECUTION_ENABLED": "false",
        "SIX_LAYER_POOLS_EXECUTION_ACTIVE": "false",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


def stage0_preflight(settings: Settings) -> dict[str, Any]:
    billing = build_billing_safety_report()
    processes = current_execution_processes()
    lock_owner = read_lock()
    mode9_processes = [proc for proc in processes if proc.process_name == "mode9_autonomous_agent"]
    duplicate_execution = len(processes) > 1
    checks = {
        "live_trading_enabled": env_bool("LIVE_TRADING_ENABLED", False),
        "paper_mode": settings.trading_mode == "PAPER",
        "execution_writer_lock_ok": bool(lock_owner and lock_owner.get("process_name") == "mode9_autonomous_agent"),
        "duplicate_execution_processes": duplicate_execution,
        "regulatory_snapshot_used": bool(billing.get("regulatory_snapshot_used")),
        "paid_snapshot_risk": bool(billing.get("paid_snapshot_risk")),
        "snapshot_request_used": bool(billing.get("snapshot_request_used")),
        "market_orders_allowed": env_bool("ALLOW_MARKET_ORDERS", False),
        "options_execution_allowed": env_bool("ALLOW_OPTIONS_EXECUTION", False),
        "buy_freeze": env_bool("MODE9_BUY_FREEZE", True),
        "pool_manager_execution_active": env_bool("SIX_LAYER_POOLS_EXECUTION_ACTIVE", False),
        "mode9_process_count": len(mode9_processes),
    }
    pass_status = (
        checks["live_trading_enabled"] is False
        and checks["paper_mode"] is True
        and checks["execution_writer_lock_ok"] is True
        and checks["duplicate_execution_processes"] is False
        and checks["regulatory_snapshot_used"] is False
        and checks["paid_snapshot_risk"] is False
        and checks["snapshot_request_used"] is False
        and checks["market_orders_allowed"] is False
        and checks["options_execution_allowed"] is False
        and checks["pool_manager_execution_active"] is False
    )
    report = {
        "timestamp": now(),
        "stage": 0,
        "stage_name": "preflight",
        "stage_status": "PASS" if pass_status else "FAIL",
        "checks": checks,
        "active_execution_processes": [proc.__dict__ | {"process_name": proc.process_name} for proc in processes],
        "lock_owner": lock_owner,
        "blocked_reason": "" if pass_status else failed_checks(checks, {
            "live_trading_enabled": False,
            "paper_mode": True,
            "execution_writer_lock_ok": True,
            "duplicate_execution_processes": False,
            "regulatory_snapshot_used": False,
            "paid_snapshot_risk": False,
            "snapshot_request_used": False,
            "market_orders_allowed": False,
            "options_execution_allowed": False,
            "pool_manager_execution_active": False,
        }),
        "orders_submitted": 0,
        "orders_cancelled": 0,
    }
    write_stage("stage0_preflight", report)
    return report


def stage1_readiness(settings: Settings) -> dict[str, Any]:
    symbols = current_position_and_open_order_symbols(settings)
    contract_details = fetch_ibkr_contract_details(
        symbols,
        host=settings.tws_host,
        port=settings.tws_port,
        client_id=settings.tws_client_id + 1965,
        timeout=float(os.getenv("MARKET_SESSION_CONTRACT_DETAILS_TIMEOUT", "4.0")),
    )
    market_session = write_market_session_report(symbols=symbols, contract_details=contract_details)
    if market_session_blocks_quote_wait(market_session):
        report = {
            "timestamp": now(),
            "stage": 1,
            "stage_name": "readiness",
            "stage_status": "FAIL",
            "blocked_by": "market_session",
            "blocked_reason": market_session.get("blocked_reason") or "market session does not allow quote wait",
            "market_session": market_session,
            "checks": {
                "account_execution_ready": False,
                "force_refresh_ok": False,
                "quotes_ready": False,
                "live_quote_confirmed": False,
                "positions_ready": None,
                "open_orders_ready": None,
                "protection_coverage_ready": None,
                "pnl_ready": None,
                "regulatory_snapshot_used": False,
                "paid_snapshot_risk": False,
                "state_stale": None,
                "market_session_allows_quote_wait": False,
                "expected_live_bid_ask": bool(market_session.get("expected_live_bid_ask")),
            },
            "quote_attempts": [],
            "orders_submitted": 0,
            "orders_cancelled": 0,
        }
        write_stage("stage1_readiness", report)
        return report

    run_record_account_pnl_once()
    build_account_reports_main()
    force: dict[str, Any] = {}
    account = None
    readiness: dict[str, Any] = {}
    attempts: list[dict[str, Any]] = []
    max_attempts = int(os.getenv("FULL_PAPER_ROLLOUT_STAGE1_QUOTE_ATTEMPTS", "3"))
    wait_seconds = float(os.getenv("FULL_PAPER_ROLLOUT_STAGE1_STREAM_WAIT_SECONDS", "5.0"))
    retry_sleep = float(os.getenv("FULL_PAPER_ROLLOUT_STAGE1_RETRY_SLEEP_SECONDS", "2.0"))
    original_wait = os.getenv("ACCOUNT_STATE_STREAMING_WAIT_SECONDS")
    try:
        os.environ["ACCOUNT_STATE_STREAMING_WAIT_SECONDS"] = str(wait_seconds)
        for attempt in range(1, max_attempts + 1):
            force = build_force_refresh_dry_run(settings=settings)
            account = build_account_state(settings=settings, force_refresh=False, write_reports_enabled=True)
            readiness = read_json(PROJECT_ROOT / "reports" / "account_execution_readiness" / "latest.json")
            diagnostics = read_json(PROJECT_ROOT / "reports" / "streaming_quote_diagnostics" / "latest.json")
            attempts.append({
                "attempt": attempt,
                "force_refresh_ok": bool(force.get("force_refresh_ok")),
                "account_execution_ready": bool(readiness.get("account_execution_ready")),
                "quotes_ready": bool(readiness.get("quotes_ready")),
                "live_quote_confirmed": bool(readiness.get("live_quote_confirmed")),
                "blocking_reasons": readiness.get("blocking_reasons", []),
                "streaming_timestamp": diagnostics.get("timestamp"),
                "streaming_rows": [
                    {
                        "symbol": row.get("symbol"),
                        "bid_received": row.get("bid_received"),
                        "ask_received": row.get("ask_received"),
                        "last_received": row.get("last_received"),
                        "bid": row.get("bid"),
                        "ask": row.get("ask"),
                        "last": row.get("last"),
                        "bid_age_sec": row.get("bid_age_sec"),
                        "ask_age_sec": row.get("ask_age_sec"),
                        "blocked_reason": row.get("blocked_reason"),
                    }
                    for row in diagnostics.get("rows", [])
                    if isinstance(row, Mapping)
                ],
            })
            if readiness.get("account_execution_ready") is True and force.get("force_refresh_ok") is True:
                break
            if attempt < max_attempts:
                time.sleep(retry_sleep)
    finally:
        if original_wait is None:
            os.environ.pop("ACCOUNT_STATE_STREAMING_WAIT_SECONDS", None)
        else:
            os.environ["ACCOUNT_STATE_STREAMING_WAIT_SECONDS"] = original_wait
    billing = read_json(PROJECT_ROOT / "reports" / "market_data_billing_safety" / "latest.json")
    state_stale = bool(account.state_stale) if account is not None else True
    checks = {
        "account_execution_ready": bool(readiness.get("account_execution_ready")),
        "force_refresh_ok": bool(force.get("force_refresh_ok")),
        "quotes_ready": bool(readiness.get("quotes_ready")),
        "live_quote_confirmed": bool(readiness.get("live_quote_confirmed")),
        "positions_ready": bool(readiness.get("positions_ready")),
        "open_orders_ready": bool(readiness.get("open_orders_ready")),
        "protection_coverage_ready": bool(readiness.get("protection_coverage_ready")),
        "pnl_ready": bool(readiness.get("pnl_ready")),
        "regulatory_snapshot_used": bool(readiness.get("regulatory_snapshot_used") or force.get("regulatory_snapshot_used") or billing.get("regulatory_snapshot_used")),
        "paid_snapshot_risk": bool(readiness.get("paid_snapshot_used") or force.get("paid_market_data_request_used") or billing.get("paid_snapshot_risk")),
        "state_stale": state_stale,
    }
    pass_status = (
        all(checks[key] is True for key in [
            "account_execution_ready",
            "force_refresh_ok",
            "quotes_ready",
            "live_quote_confirmed",
            "positions_ready",
            "open_orders_ready",
            "protection_coverage_ready",
            "pnl_ready",
        ])
        and checks["regulatory_snapshot_used"] is False
        and checks["paid_snapshot_risk"] is False
        and checks["state_stale"] is False
    )
    report = {
        "timestamp": now(),
        "stage": 1,
        "stage_name": "readiness",
        "stage_status": "PASS" if pass_status else "FAIL",
        "checks": checks,
        "market_session": market_session,
        "quote_attempts": attempts,
        "force_refresh": force,
        "account_execution_readiness": readiness,
        "blocked_reason": "" if pass_status else "; ".join(readiness.get("blocking_reasons", [])) or "stage1 readiness checks failed",
        "orders_submitted": 0,
        "orders_cancelled": 0,
    }
    write_stage("stage1_readiness", report)
    return report


def current_position_and_open_order_symbols(settings: Settings) -> list[str]:
    symbols: list[str] = []
    try:
        guard = build_position_guard_report(settings=settings)
        for row in guard.get("symbols", []):
            if isinstance(row, Mapping) and float(row.get("position_qty") or 0) != 0:
                symbols.append(str(row.get("symbol", "")).upper())
    except Exception:
        pass
    try:
        orders = read_tws_orders(
            host=settings.tws_host,
            port=settings.tws_port,
            client_id=settings.tws_client_id + 1960,
            timeout=settings.tws_status_timeout,
        )
        for order in orders.get("open_orders", []):
            if isinstance(order, Mapping):
                symbols.append(str(order.get("symbol", "")).upper())
    except Exception:
        pass
    return [symbol for symbol in dict.fromkeys(symbols) if symbol]


def market_session_blocks_quote_wait(market_session: Mapping[str, Any]) -> bool:
    state = str(market_session.get("session_state") or "").upper()
    if state in {"CLOSED", "WEEKEND", "HOLIDAY", "UNKNOWN"}:
        return True
    return market_session.get("allows_quote_wait") is False


def stage2_protective_repair(settings: Settings) -> dict[str, Any]:
    force = build_force_refresh_dry_run(settings=settings)
    if not force.get("force_refresh_ok"):
        report = {
            "timestamp": now(),
            "stage": 2,
            "stage_name": "protective_repair",
            "stage_status": "FAIL",
            "blocked_reason": force.get("blocked_reason") or "force refresh failed before stage2",
            "force_refresh": force,
            "orders_submitted": 0,
            "orders_cancelled": 0,
        }
        write_stage("stage2_protective_repair", report)
        return report

    guard = build_position_guard_report(settings=settings)
    symbols = [row["symbol"] for row in guard.get("symbols", []) if isinstance(row, Mapping) and float(row.get("position_qty") or 0) > 0]
    diagnostics = refresh_streaming_quote_diagnostics(settings=settings, symbols=symbols)
    guard = overlay_streaming_quotes(guard, diagnostics)
    preview = build_repair_preview_report(
        settings=settings,
        guard_report=guard,
        stop_config=load_stop_config(),
        repair_config=load_repair_config(enabled=False),
    )
    candidates = [row for row in preview.get("proposals", []) if row.get("execution_preview_allowed") is True]
    candidates = candidates[: int(os.getenv("FULL_PAPER_ROLLOUT_STAGE2_MAX_ORDERS", "20"))]

    precheck_error = stage2_precheck(preview, candidates)
    submitted: list[dict[str, Any]] = []
    errors: list[str] = []
    if precheck_error:
        return stage2_blocked(force, preview, precheck_error)

    broker = TwsPaperBroker(settings.tws_host, settings.tws_port, settings.tws_client_id + 1940)
    for item in candidates:
        symbol = str(item.get("symbol", "")).upper()
        qty = int(float(item.get("recommended_qty") or 0))
        stop_price = float(item.get("proposed_stop_price") or 0)
        limit_price = float(item.get("normalized_limit_price") or 0)
        order_ref = f"rollout-protect-{symbol.lower()}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"[:64]
        try:
            confirmation = broker.submit_stop_limit(
                symbol=symbol,
                action="SELL",
                quantity=qty,
                stop_price=stop_price,
                limit_price=limit_price,
                order_ref=order_ref,
                transmit=True,
                outside_rth=True,
            )
            submitted.append({
                "symbol": symbol,
                "side": "SELL",
                "order_type": "STP LMT",
                "qty": qty,
                "stop_price": confirmation.normalized_stop_price,
                "limit_price": confirmation.normalized_limit_price,
                "order_ref": order_ref,
                "order_ids": list(confirmation.order_ids),
                "acknowledged_order_ids": list(confirmation.acknowledged_ids),
                "statuses": confirmation.statuses,
                "open_order_states": confirmation.open_order_states,
                "messages": list(confirmation.messages),
                "outsideRth_requested": True,
            })
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{symbol}: {exc}")
            break

    readback = read_tws_orders(
        host=settings.tws_host,
        port=settings.tws_port,
        client_id=settings.tws_client_id + 1950,
        timeout=settings.tws_status_timeout,
    )
    result = build_stage2_result(force=force, preview=preview, submitted=submitted, readback=readback, errors=errors)
    write_position_protection_execution_result(result)
    write_stage("stage2_protective_repair", result)
    return result


def run_record_account_pnl_once() -> None:
    old_argv = sys.argv[:]
    try:
        sys.argv = [
            "record_account_pnl.py",
            "--samples",
            "1",
            "--timeout",
            "8",
            "--interval-seconds",
            "1",
        ]
        record_account_pnl_main()
    finally:
        sys.argv = old_argv


def stage2_precheck(preview: Mapping[str, Any], candidates: list[Mapping[str, Any]]) -> str:
    if env_bool("LIVE_TRADING_ENABLED", False):
        return "LIVE_TRADING_ENABLED must remain false"
    if not env_bool("MODE9_BUY_FREEZE", True):
        return "MODE9_BUY_FREEZE must remain true"
    if env_bool("ALLOW_MARKET_ORDERS", False):
        return "ALLOW_MARKET_ORDERS must remain false"
    if env_bool("ALLOW_OPTIONS_EXECUTION", False):
        return "ALLOW_OPTIONS_EXECUTION must remain false"
    for item in candidates:
        if item.get("recommended_order_type") != "SELL STP LMT":
            return f"{item.get('symbol')}: recommended_order_type is not SELL STP LMT"
        if int(float(item.get("recommended_qty") or 0)) <= 0:
            return f"{item.get('symbol')}: recommended_qty <= 0"
        if float(item.get("existing_protective_qty") or 0) + int(float(item.get("recommended_qty") or 0)) > float(item.get("position_qty") or 0):
            return f"{item.get('symbol')}: total protection would exceed position"
        if item.get("duplicate_protection_detected") is True:
            return f"{item.get('symbol')}: duplicate protection detected"
        if float(item.get("overprotected_qty") or 0) > 0:
            return f"{item.get('symbol')}: overprotected"
        if not item.get("bid") or not item.get("ask"):
            return f"{item.get('symbol')}: missing live bid/ask"
        if not item.get("proposed_stop_price") or not item.get("normalized_limit_price"):
            return f"{item.get('symbol')}: missing stop/limit price"
    if not candidates:
        return "no eligible protective repair candidates"
    return ""


def stage2_blocked(force: Mapping[str, Any], preview: Mapping[str, Any], reason: str) -> dict[str, Any]:
    report = {
        "timestamp": now(),
        "stage": 2,
        "stage_name": "protective_repair",
        "stage_status": "FAIL",
        "blocked_reason": reason,
        "force_refresh": force,
        "repair_preview": preview,
        "orders_submitted": 0,
        "orders_cancelled": 0,
    }
    write_stage("stage2_protective_repair", report)
    return report


def build_stage2_result(
    *,
    force: Mapping[str, Any],
    preview: Mapping[str, Any],
    submitted: list[Mapping[str, Any]],
    readback: Mapping[str, Any],
    errors: list[str],
) -> dict[str, Any]:
    submitted_refs = {str(row.get("order_ref")) for row in submitted}
    readback_orders = [
        order for order in readback.get("open_orders", [])
        if str(order.get("order_ref")) in submitted_refs
    ]
    readback_by_ref = {str(order.get("order_ref")): order for order in readback_orders}
    readback_checks = []
    for row in submitted:
        order = readback_by_ref.get(str(row.get("order_ref")))
        readback_checks.append({
            "symbol": row.get("symbol"),
            "order_ref": row.get("order_ref"),
            "readback_found": order is not None,
            "side_sell": bool(order and order.get("action") == "SELL"),
            "order_type_stp_lmt": bool(order and order.get("order_type") == "STP LMT"),
            "tif_gtc": bool(order and order.get("tif") == "GTC"),
            "outsideRth_requested": True,
            "outsideRth_effective": None if order is None else order.get("outside_rth"),
            "qty_matches": bool(order and int(float(order.get("total_quantity") or 0)) == int(float(row.get("qty") or 0))),
            "stop_matches": bool(order and float(order.get("aux_price") or 0) == float(row.get("stop_price") or 0)),
            "limit_matches": bool(order and float(order.get("limit_price") or 0) == float(row.get("limit_price") or 0)),
            "active_status": bool(order and str(order.get("status")) in ACTIVE_ORDER_STATUSES),
            "raw_readback": order,
        })
    readback_ok = bool(readback_checks) and all(
        check["readback_found"]
        and check["side_sell"]
        and check["order_type_stp_lmt"]
        and check["tif_gtc"]
        and check["qty_matches"]
        and check["stop_matches"]
        and check["limit_matches"]
        and check["active_status"]
        for check in readback_checks
    )
    after_coverage = protection_after_readback(preview, readback)
    protection_ok = all(row["total_active_sell_protection_qty"] <= row["position_qty"] for row in after_coverage)
    no_bad_orders = {
        "buy_orders_submitted": 0,
        "live_orders_submitted": 0,
        "market_orders_submitted": 0,
        "options_orders_submitted": 0,
    }
    pass_status = not errors and readback_ok and protection_ok
    report = {
        "timestamp": now(),
        "stage": 2,
        "stage_name": "protective_repair",
        "stage_status": "PASS" if pass_status else "FAIL",
        "blocked_reason": "" if pass_status else "; ".join(errors) or "readback/protection check failed",
        "force_refresh": force,
        "repair_preview_timestamp": preview.get("timestamp"),
        "orders_submitted": len(submitted),
        "orders_cancelled": 0,
        "paper_protective_sell_stp_lmt_submitted": submitted,
        **no_bad_orders,
        "all_submitted_orders_are_paper_protective_sell_stp_lmt": all(row.get("order_type") == "STP LMT" and row.get("side") == "SELL" for row in submitted),
        "readback_ok": readback_ok,
        "readback_checks": readback_checks,
        "total_active_sell_protection_after_repair": after_coverage,
        "protection_after_repair_ok": protection_ok,
        "outsideRth_requested": True if submitted else False,
        "outsideRth_effective": [check.get("outsideRth_effective") for check in readback_checks],
        "warnings": [message for row in submitted for message in row.get("messages", [])],
        "errors": errors,
    }
    return report


def protection_after_readback(preview: Mapping[str, Any], readback: Mapping[str, Any]) -> list[dict[str, Any]]:
    result = []
    for row in preview.get("proposals", []):
        symbol = str(row.get("symbol", "")).upper()
        position_qty = float(row.get("position_qty") or 0)
        protection_qty = 0.0
        for order in readback.get("open_orders", []):
            if str(order.get("symbol", "")).upper() != symbol:
                continue
            if str(order.get("action", "")).upper() != "SELL":
                continue
            if not str(order.get("order_type", "")).upper().startswith("STP"):
                continue
            if str(order.get("status")) not in ACTIVE_ORDER_STATUSES:
                continue
            protection_qty += float(order.get("total_quantity") or 0)
        result.append({
            "symbol": symbol,
            "position_qty": position_qty,
            "total_active_sell_protection_qty": protection_qty,
            "ok": protection_qty <= position_qty,
        })
    return result


def write_position_protection_execution_result(report: Mapping[str, Any]) -> None:
    POSITION_PROTECTION_DIR.mkdir(parents=True, exist_ok=True)
    (POSITION_PROTECTION_DIR / "repair_execution_result.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    (POSITION_PROTECTION_DIR / "repair_execution_result.md").write_text(stage_md(report), encoding="utf-8")


def write_stage(name: str, report: Mapping[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / f"{name}.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    (REPORT_DIR / f"{name}.md").write_text(stage_md(report), encoding="utf-8")


def write_summary(stages: list[Mapping[str, Any]]) -> None:
    payload = {
        "timestamp": now(),
        "source": "full_paper_rollout",
        "stages": stages,
        "passed_stages": [stage.get("stage") for stage in stages if stage.get("stage_status") == "PASS"],
        "failed_stages": [stage.get("stage") for stage in stages if stage.get("stage_status") != "PASS"],
        "live_orders_submitted": 0,
        "market_orders_submitted": sum(int(stage.get("market_orders_submitted", 0) or 0) for stage in stages),
        "options_orders_submitted": sum(int(stage.get("options_orders_submitted", 0) or 0) for stage in stages),
        "orders_submitted": sum(int(stage.get("orders_submitted", 0) or 0) for stage in stages),
        "orders_cancelled": sum(int(stage.get("orders_cancelled", 0) or 0) for stage in stages),
    }
    (REPORT_DIR / "latest.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    (REPORT_DIR / "latest.md").write_text(stage_md(payload), encoding="utf-8")


def stage_md(report: Mapping[str, Any]) -> str:
    lines = [
        f"# {report.get('source') or report.get('stage_name') or 'Full Paper Rollout'}",
        "",
        f"- timestamp: {report.get('timestamp')}",
    ]
    for key in [
        "stage",
        "stage_status",
        "blocked_reason",
        "orders_submitted",
        "orders_cancelled",
        "buy_orders_submitted",
        "market_orders_submitted",
        "options_orders_submitted",
        "readback_ok",
    ]:
        if key in report:
            lines.append(f"- {key}: {report.get(key)}")
    if "checks" in report:
        lines.extend(["", "## Checks", "", "| Check | Value |", "|---|---|"])
        for key, value in report.get("checks", {}).items():
            lines.append(f"| {key} | {value} |")
    if "paper_protective_sell_stp_lmt_submitted" in report:
        lines.extend(["", "## Submitted Protective Orders", "", "| Symbol | Qty | Stop | Limit | Order Ref |", "|---|---:|---:|---:|---|"])
        for row in report.get("paper_protective_sell_stp_lmt_submitted", []):
            lines.append(f"| {row.get('symbol')} | {row.get('qty')} | {row.get('stop_price')} | {row.get('limit_price')} | {row.get('order_ref')} |")
    return "\n".join(lines) + "\n"


def failed_checks(actual: Mapping[str, Any], expected: Mapping[str, Any]) -> str:
    failures = []
    for key, value in expected.items():
        if actual.get(key) != value:
            failures.append(f"{key} expected {value} got {actual.get(key)}")
    return "; ".join(failures)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
