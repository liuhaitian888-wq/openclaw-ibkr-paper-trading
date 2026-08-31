"""Freshness policy for simulation and future IBKR paper execution readiness."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from trading.config import PROJECT_ROOT
from trading.realtime_account_state_bus import RealtimeAccountStateBus, StateUpdate


REPORT_DIR = PROJECT_ROOT / "reports" / "state_freshness_policy"


@dataclass(frozen=True)
class FreshnessThresholds:
    quote_max_age_sec: float = 2.0
    pnl_max_age_sec: float = 5.0
    position_max_age_sec: float = 5.0
    open_orders_max_age_sec: float = 5.0
    account_max_age_sec: float = 5.0
    micro_cycle_interval_sec: float = 1.0

    @classmethod
    def from_env(cls) -> "FreshnessThresholds":
        return cls(
            quote_max_age_sec=float(os.getenv("PAPER_EXECUTION_QUOTE_MAX_AGE_SEC", "2")),
            pnl_max_age_sec=float(os.getenv("PAPER_EXECUTION_PNL_MAX_AGE_SEC", "5")),
            position_max_age_sec=float(os.getenv("PAPER_EXECUTION_POSITION_MAX_AGE_SEC", "5")),
            open_orders_max_age_sec=float(os.getenv("PAPER_EXECUTION_OPEN_ORDERS_MAX_AGE_SEC", "5")),
            account_max_age_sec=float(os.getenv("PAPER_EXECUTION_ACCOUNT_MAX_AGE_SEC", "5")),
            micro_cycle_interval_sec=float(os.getenv("MICRO_CYCLE_INTERVAL_SEC", "1")),
        )


def evaluate_freshness(
    bus: RealtimeAccountStateBus,
    *,
    side: str,
    mode: str = "SIMULATION",
    thresholds: FreshnessThresholds | None = None,
) -> dict[str, Any]:
    thresholds = thresholds or FreshnessThresholds.from_env()
    if mode == "SIMULATION":
        result = {
            "mode": "SIMULATION_ONLY",
            "execution_ready": True,
            "cached_fixture_state_allowed": True,
            "blocked_reasons": [],
            "thresholds": asdict(thresholds),
        }
        write_report(result)
        return result
    checks = {
        "stale_quote": is_stale(bus.latest_quote_state, thresholds.quote_max_age_sec),
        "stale_pnl": is_stale(bus.latest_pnl_state, thresholds.pnl_max_age_sec),
        "stale_position": is_stale(bus.latest_position_state, thresholds.position_max_age_sec),
        "stale_account": is_stale(bus.latest_account_state, thresholds.account_max_age_sec),
        "stale_open_orders": is_stale(bus.latest_open_order_state, thresholds.open_orders_max_age_sec),
    }
    quote_payload: Mapping[str, Any] = bus.latest_quote_state.payload if bus.latest_quote_state else {}
    if side == "SELL" and not quote_payload.get("bid"):
        checks["stale_bid"] = True
    if side == "BUY" and not quote_payload.get("ask"):
        checks["stale_ask"] = True
    blocked = [reason for reason, blocked in checks.items() if blocked]
    result = {
        "mode": "IBKR_PAPER_READINESS",
        "side": side,
        "execution_ready": not blocked,
        "blocked_reasons": blocked,
        "thresholds": asdict(thresholds),
        "market_session_must_be_active": True,
        "process_guard_must_be_ok": True,
        "execution_lock_must_be_ok": True,
        "fixed_30_second_cycle_used_for_execution": False,
    }
    write_report(result)
    return result


def is_stale(update: StateUpdate | None, max_age_sec: float) -> bool:
    if update is None:
        return True
    return bool(update.stale_flag or update.freshness_age_sec > max_age_sec)


def write_report(payload: Mapping[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "latest.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    lines = [
        "# State Freshness Policy",
        "",
        f"- mode: {payload.get('mode')}",
        f"- execution_ready: {payload.get('execution_ready')}",
        f"- blocked_reasons: {payload.get('blocked_reasons')}",
        "- fixed_30_second_cycle_used_for_execution: False",
    ]
    (REPORT_DIR / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
