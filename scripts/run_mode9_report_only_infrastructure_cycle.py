#!/usr/bin/env python3
"""Refresh Mode 9 report-only infrastructure without submitting orders."""

import json
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_mode9_infrastructure_status import build_all_reports
from scripts.build_market_data_billing_safety import build_report as build_market_data_billing_safety_report, write_report as write_market_data_billing_safety_report
from trading.account_state_manager import build_account_state, build_force_refresh_dry_run
from trading.config import Settings
from trading.event_risk_control import build_event_risk_report
from trading.event_router import build_event_router_report
from trading.gap_escape_manager import build_gap_escape_report
from trading.gap_risk_manager import build_gap_risk_report
from trading.options_hedge_planner import build_options_hedge_report
from trading.pool_manager import build_pool_manager_report
from trading.position_guard import build_position_guard_report
from trading.position_protection import run_position_protection
from trading.profit_lock import build_profit_lock_report
from trading.take_profit import build_take_profit_report
from trading.trailing_profit import build_trailing_profit_report


REPORT_DIR = PROJECT_ROOT / "reports" / "mode9_report_only_infrastructure_cycle"


def main() -> int:
    payload = run_report_only_cycle()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "latest.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    with (REPORT_DIR / "history.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
    print(json.dumps({"status": payload["status"], "report_path": str(REPORT_DIR / "latest.json")}, indent=2, sort_keys=True))
    return 0


def run_report_only_cycle() -> dict[str, Any]:
    settings = Settings.load()
    reports: dict[str, Any] = {}
    errors: list[str] = []

    billing = capture("market_data_billing_safety", reports, errors, lambda: write_and_return_billing_safety())
    account_state = capture("account_state_manager", reports, errors, lambda: build_account_state(settings=settings, force_refresh=False))
    position_guard = capture("position_guard", reports, errors, lambda: build_position_guard_report(settings=settings))
    mark_state_usage(reports, "position_guard", False, "position_guard still performs direct read-only refresh")
    pool_manager = capture("pool_manager", reports, errors, lambda: build_pool_manager_report(position_guard=position_guard))
    mark_state_usage(reports, "pool_manager", True, "account_state_manager positions are represented through refreshed position_guard fallback")
    event_risk = capture("event_risk", reports, errors, lambda: build_event_risk_report(position_guard=position_guard))
    mark_state_usage(reports, "event_risk", True, "uses AccountState-derived position_guard fallback")
    gap_risk = capture("gap_risk", reports, errors, lambda: build_gap_risk_report(position_guard=position_guard, event_risk_report=event_risk))
    mark_state_usage(reports, "gap_risk", True, "uses AccountState-derived position_guard fallback")
    position_protection = capture("position_protection", reports, errors, lambda: run_position_protection(settings=settings, guard_report=position_guard))
    mark_state_usage(reports, "position_protection", True, "uses AccountState-derived position_guard fallback; execution still requires force refresh")
    gap_escape = capture(
        "gap_escape",
        reports,
        errors,
        lambda: build_gap_escape_report(position_guard=position_guard, gap_risk_report=gap_risk, event_risk_report=event_risk, settings=settings),
    )
    mark_state_usage(reports, "gap_escape", True, "uses AccountState-derived position_guard fallback; execution remains disabled")
    capture(
        "event_router",
        reports,
        errors,
        lambda: build_event_router_report(
            position_guard=position_guard,
            gap_risk=gap_risk,
            gap_escape=gap_escape,
            event_risk=event_risk,
            pool_membership=pool_manager.get("membership") if isinstance(pool_manager, dict) else None,
        ),
    )
    mark_state_usage(reports, "event_router", True, "routes reports generated after account_state_manager")
    capture("profit_lock", reports, errors, lambda: build_profit_lock_report(position_guard=position_guard))
    mark_state_usage(reports, "profit_lock", True, "uses AccountState-derived position_guard fallback")
    capture("take_profit", reports, errors, lambda: build_take_profit_report(position_guard=position_guard))
    mark_state_usage(reports, "take_profit", True, "uses AccountState-derived position_guard fallback")
    capture("trailing_profit", reports, errors, lambda: build_trailing_profit_report(position_guard=position_guard))
    mark_state_usage(reports, "trailing_profit", True, "uses AccountState-derived position_guard fallback")
    capture("options_hedge", reports, errors, lambda: build_options_hedge_report(position_guard=position_guard, event_risk_report=event_risk, settings=settings))
    mark_state_usage(reports, "options_hedge", True, "uses AccountState-derived position_guard fallback; options execution disabled")
    capture("force_refresh_dry_run", reports, errors, lambda: build_force_refresh_dry_run(settings=settings))
    capture("mode9_infrastructure_status", reports, errors, build_all_reports)

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "ok" if not errors else "error",
        "paper_only": True,
        "live_trading_enabled": False,
        "buy_submitted": False,
        "orders_submitted": 0,
        "orders_cancelled": 0,
        "report_only": True,
        "paid_market_data_request_used": bool(billing.get("paid_snapshot_risk")) if isinstance(billing, dict) else False,
        "regulatory_snapshot_used": bool(billing.get("regulatory_snapshot_used")) if isinstance(billing, dict) else False,
        "account_state_stale": bool(account_state.get("state_stale")) if isinstance(account_state, dict) else True,
        "account_state_blocked_reason": account_state.get("blocked_reason") if isinstance(account_state, dict) else "account_state_manager did not return dict",
        "errors": errors,
        "reports": reports,
    }


def capture(name: str, reports: dict[str, Any], errors: list[str], func: Any) -> Any:
    try:
        result = func()
    except Exception as exc:
        result = {"status": "error", "error": str(exc)}
        errors.append(f"{name} failed: {exc}")
    reports[name] = summarize(result)
    if isinstance(result, dict):
        return result
    if is_dataclass(result):
        return asdict(result)
    return {}


def summarize(result: Any) -> dict[str, Any]:
    if is_dataclass(result):
        result = asdict(result)
    if not isinstance(result, dict):
        return {"status": "ok"}
    return {
        "status": result.get("status", "ok"),
        "source": result.get("source"),
        "timestamp": result.get("timestamp") or result.get("created_at"),
        "used_cached_state": result.get("used_cached_state"),
        "force_refresh_required": (result.get("force_refresh") or {}).get("force_refresh_required") if isinstance(result.get("force_refresh"), dict) else None,
        "force_refresh_performed": (result.get("force_refresh") or {}).get("force_refresh_performed") if isinstance(result.get("force_refresh"), dict) else None,
        "force_refresh_ok": (result.get("force_refresh") or {}).get("force_refresh_ok") if isinstance(result.get("force_refresh"), dict) else None,
        "state_stale": result.get("state_stale"),
        "blocked_reason": result.get("blocked_reason"),
        "symbol_count": len(result.get("symbols", [])) if isinstance(result.get("symbols"), list) else None,
        "action_count": len(result.get("actions", [])) if isinstance(result.get("actions"), list) else None,
        "record_count": len(result.get("records", [])) if isinstance(result.get("records"), list) else None,
    }


def mark_state_usage(reports: dict[str, Any], name: str, used: bool, reason: str) -> None:
    reports.setdefault(name, {})
    reports[name]["used_account_state_manager"] = used
    reports[name]["fallback_used"] = not used or "fallback" in reason
    reports[name]["fallback_reason"] = reason


def write_and_return_billing_safety() -> dict[str, Any]:
    report = build_market_data_billing_safety_report()
    write_market_data_billing_safety_report(report)
    return report


if __name__ == "__main__":
    raise SystemExit(main())
