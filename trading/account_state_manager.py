import csv
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from trading.config import PROJECT_ROOT, Settings
from trading.module_interfaces import (
    AccountState,
    ForceRefreshResult,
    OpenOrderState,
    PnLState,
    PositionState,
    ProtectionCoverageState,
    QuoteState,
    StateFreshness,
)
from trading.position_guard import build_position_guard_report
from trading.ibkr_streaming import IbkrStreamingQuoteSource


ACCOUNT_STATE_DIR = PROJECT_ROOT / "reports" / "account_state"
POSITION_STATE_DIR = PROJECT_ROOT / "reports" / "position_state"
QUOTE_STATE_DIR = PROJECT_ROOT / "reports" / "quote_state"
PNL_STATE_DIR = PROJECT_ROOT / "reports" / "pnl_state"
ACCOUNT_DASHBOARD_DIR = PROJECT_ROOT / "reports" / "account_dashboard"
MONITORING_LINE_DIR = PROJECT_ROOT / "reports" / "monitoring_line"
OPEN_ORDER_STATE_DIR = PROJECT_ROOT / "reports" / "open_order_state"
ACCOUNT_EXECUTION_READINESS_DIR = PROJECT_ROOT / "reports" / "account_execution_readiness"
FORCE_REFRESH_DRY_RUN_DIR = PROJECT_ROOT / "reports" / "force_refresh_dry_run"
STREAMING_QUOTE_DIAGNOSTICS_DIR = PROJECT_ROOT / "reports" / "streaming_quote_diagnostics"

DEFAULT_STALE_SEC = 60.0
DEFAULT_QUOTE_STALE_SEC = 10.0
QUOTE_FRESHNESS_THRESHOLDS_SEC = {
    "DASHBOARD": 900.0,
    "MONITORING": 120.0,
    "PROTECTION_PLANNING": 30.0,
    "EXECUTION_GATE": 5.0,
    "GAP_ESCAPE": 2.0,
}
QUOTE_USE_CASES = tuple(QUOTE_FRESHNESS_THRESHOLDS_SEC)
MARKET_DATA_TYPE_NAMES = {1: "live", 2: "frozen", 3: "delayed", 4: "delayed_frozen"}


def build_account_state(
    *,
    settings: Settings | None = None,
    force_refresh: bool = False,
    position_guard_report: Mapping[str, Any] | None = None,
    account_snapshot: Mapping[str, Any] | None = None,
    streaming_diagnostics: Mapping[str, Any] | None = None,
    write_reports_enabled: bool = True,
) -> AccountState:
    settings = settings or Settings.load()
    force_result = force_refresh_state(settings=settings, perform=force_refresh)
    if force_refresh and force_result.force_refresh_ok:
        position_guard_report = read_json(PROJECT_ROOT / "reports" / "position_guard" / "latest.json")
    guard = dict(position_guard_report or read_json(PROJECT_ROOT / "reports" / "position_guard" / "latest.json"))
    if streaming_diagnostics is None and position_guard_report is None and env_bool("ACCOUNT_STATE_STREAMING_REFRESH_ENABLED", True):
        streaming_diagnostics = refresh_streaming_quote_diagnostics(settings=settings, symbols=symbols_from_guard(guard))
    if streaming_diagnostics:
        guard = overlay_streaming_quotes(guard, streaming_diagnostics)
    account = dict(account_snapshot or read_json(PROJECT_ROOT / "reports" / "account" / "latest.json"))
    orders = dict(read_json(PROJECT_ROOT / "reports" / "list_tws_orders_latest.json"))
    protection = dict(read_json(PROJECT_ROOT / "reports" / "position_protection" / "latest.json"))
    repair_preview = dict(read_json(PROJECT_ROOT / "reports" / "position_protection" / "repair_preview.json"))
    pnl_latest = latest_pnl_row()
    now = utc_now()

    freshness = build_freshness(
        account_path=PROJECT_ROOT / "reports" / "account" / "latest.json",
        positions_path=PROJECT_ROOT / "reports" / "position_guard" / "latest.json",
        open_orders_path=PROJECT_ROOT / "reports" / "list_tws_orders_latest.json",
        pnl_path=PROJECT_ROOT / "reports" / "pnl_timeseries.csv",
        protection_path=PROJECT_ROOT / "reports" / "position_protection" / "latest.json",
        position_rows=guard.get("symbols", []),
    )
    if isinstance(guard.get("open_orders"), list):
        freshness = StateFreshness(
            account_summary_age_sec=freshness.account_summary_age_sec,
            positions_age_sec=freshness.positions_age_sec,
            open_orders_age_sec=freshness.positions_age_sec,
            quotes_age_sec=freshness.quotes_age_sec,
            pnl_age_sec=freshness.pnl_age_sec,
            protection_coverage_age_sec=freshness.protection_coverage_age_sec,
        )
    quotes = build_quote_states(guard.get("symbols", []), now=now)
    positions = [position_state_from_guard(row, now=now, freshness=freshness) for row in guard.get("symbols", []) if isinstance(row, Mapping) and float(row.get("position_qty") or 0) != 0]
    open_order_rows = guard.get("open_orders") if isinstance(guard.get("open_orders"), list) else orders.get("open_orders", [])
    open_orders = [open_order_state(row, now=now, age=freshness.open_orders_age_sec) for row in open_order_rows if isinstance(row, Mapping)]
    coverage = [coverage_state(row, now=now, age=freshness.protection_coverage_age_sec) for row in guard.get("symbols", []) if isinstance(row, Mapping) and float(row.get("position_qty") or 0) > 0]
    pnl = build_pnl_states(account=account, latest_pnl=pnl_latest, positions=positions, now=now, pnl_age_sec=freshness.pnl_age_sec)

    state_stale, blocked_reason = stale_status(freshness)
    if force_refresh and not force_result.force_refresh_ok:
        state_stale = True
        blocked_reason = force_result.blocked_reason
    state = AccountState(
        timestamp=now,
        mode=settings.trading_mode,
        account_id=str(account.get("account") or guard.get("account") or pnl_latest.get("account") or ""),
        net_liquidation=float_or_none(account.get("net_liquidation") or pnl_latest.get("net_liquidation")),
        cash=float_or_none(account.get("cash") or pnl_latest.get("total_cash_value")),
        buying_power=float_or_none(account.get("buying_power") or pnl_latest.get("buying_power")),
        gross_position_value=float_or_none(pnl_latest.get("gross_position_value")) or sum_float(item.market_value for item in positions),
        realized_pnl=float_or_none(account.get("realized_pnl") or pnl_latest.get("realized_pnl")),
        unrealized_pnl=float_or_none(account.get("unrealized_pnl") or pnl_latest.get("unrealized_pnl")),
        positions=positions,
        quotes=quotes,
        open_orders=open_orders,
        pnl=pnl,
        protection_coverage=coverage,
        freshness=freshness,
        state_stale=state_stale,
        blocked_reason=blocked_reason,
        used_cached_state=not force_refresh,
        force_refresh=force_result,
        metadata={
            "source": "account_state_manager",
            "report_only": True,
            "orders_submitted": 0,
            "orders_cancelled": 0,
            "used_position_guard_report": bool(guard),
            "used_account_report": bool(account),
            "used_orders_snapshot": bool(orders),
            "used_repair_preview": bool(repair_preview),
            "position_guard_status": guard.get("status"),
            "position_protection_enabled": protection.get("position_protection_repair_enabled"),
        },
    )
    if write_reports_enabled:
        write_account_state_reports(state)
    return state


def force_refresh_state(*, settings: Settings | None = None, perform: bool = True) -> ForceRefreshResult:
    if not perform:
        return ForceRefreshResult(False, False, True, False, False, False, False, False, "")
    settings = settings or Settings.load()
    try:
        guard = build_position_guard_report(settings=settings)
    except Exception as exc:
        return ForceRefreshResult(True, True, False, False, False, False, False, False, f"force refresh failed: {exc}")
    diagnostics = refresh_streaming_quote_diagnostics(settings=settings, symbols=symbols_from_guard(guard))
    guard = overlay_streaming_quotes(guard, diagnostics)
    ok = guard.get("status") in {"ok", "warning"} and bool(guard.get("symbols") is not None)
    sell_quote_results = [
        quote_execution_readiness(row, side="SELL", use_case="EXECUTION_GATE")
        for row in guard.get("symbols", [])
        if isinstance(row, Mapping) and float(row.get("position_qty") or 0) > 0
    ]
    quotes_ok = all(item["ok"] for item in sell_quote_results)
    protection_ok = all("protective_stop_qty" in row for row in guard.get("symbols", []) if isinstance(row, Mapping))
    blocked = ""
    if not ok:
        blocked = f"position/open-order force refresh status is {guard.get('status')}"
    elif not quotes_ok:
        blocked = "; ".join(item["blocked_reason"] for item in sell_quote_results if not item["ok"]) or "force refresh completed but at least one execution quote is stale"
    elif not protection_ok:
        blocked = "force refresh completed but protection coverage is missing"
    return ForceRefreshResult(
        force_refresh_required=True,
        force_refresh_performed=True,
        force_refresh_ok=ok and quotes_ok and protection_ok,
        positions_refreshed=ok,
        open_orders_refreshed=ok,
        quotes_refreshed=quotes_ok,
        pnl_refreshed=False,
        protection_coverage_refreshed=protection_ok,
        blocked_reason=blocked,
    )


def build_force_refresh_dry_run(*, settings: Settings | None = None) -> dict[str, Any]:
    result = force_refresh_state(settings=settings, perform=True)
    account_state = build_account_state(settings=settings, force_refresh=False, write_reports_enabled=True)
    payload = {
        "timestamp": utc_now(),
        "source": "force_refresh_dry_run",
        "force_refresh_performed": result.force_refresh_performed,
        "force_refresh_ok": result.force_refresh_ok,
        "positions_refreshed": result.positions_refreshed,
        "open_orders_refreshed": result.open_orders_refreshed,
        "quotes_refreshed": result.quotes_refreshed,
        "pnl_refreshed": result.pnl_refreshed,
        "protection_coverage_refreshed": result.protection_coverage_refreshed,
        "state_stale_after_refresh": account_state.state_stale,
        "execution_ready_after_refresh": account_execution_readiness_payload(account_state)["account_execution_ready"],
        "blocked_reason": result.blocked_reason or account_state.blocked_reason,
        "paid_market_data_request_used": False,
        "regulatory_snapshot_used": False,
        "orders_submitted": 0,
        "orders_cancelled": 0,
    }
    write_json_report(FORCE_REFRESH_DRY_RUN_DIR, payload, markdown=force_refresh_dry_run_md(payload))
    return payload


def refresh_streaming_quote_diagnostics(*, settings: Settings | None = None, symbols: list[str] | None = None) -> dict[str, Any]:
    settings = settings or Settings.load()
    symbols = list(dict.fromkeys(symbol.upper() for symbol in (symbols or []) if symbol))
    if not symbols:
        payload = {"timestamp": utc_now(), "source": "streaming_quote_diagnostics", "symbols": [], "rows": [], "errors": ["no symbols requested"]}
        write_streaming_quote_diagnostics(payload)
        return payload
    source = IbkrStreamingQuoteSource(
        symbols=symbols,
        host=settings.streaming_tws_host,
        port=settings.streaming_tws_port,
        client_id=int(os.getenv("ACCOUNT_STATE_STREAMING_CLIENT_ID", str(settings.streaming_client_id + 1000))),
        stale_ms=settings.streaming_stale_ms,
        max_symbols=int(os.getenv("ACCOUNT_STATE_STREAMING_MAX_SYMBOLS", str(max(len(symbols), settings.streaming_max_symbols)))),
        market_data_type=1,
        exchange=os.getenv("ACCOUNT_STATE_STREAMING_EXCHANGE", "SMART"),
    )
    started = source.start(timeout=settings.tws_status_timeout)
    wait_sec = float(os.getenv("ACCOUNT_STATE_STREAMING_WAIT_SECONDS", "2.0"))
    if started and wait_sec > 0:
        import time

        time.sleep(wait_sec)
    diagnostics = source.diagnostics()
    diagnostics["streaming_requested_symbols"] = symbols
    diagnostics["streaming_request_started"] = started
    diagnostics["snapshot_request_used"] = False
    diagnostics["regulatory_snapshot_used"] = False
    diagnostics["paid_snapshot_risk"] = False
    source.stop()
    write_streaming_quote_diagnostics(diagnostics)
    return diagnostics


def overlay_streaming_quotes(guard: Mapping[str, Any], diagnostics: Mapping[str, Any]) -> dict[str, Any]:
    updated = dict(guard)
    rows_by_symbol = {
        str(row.get("symbol", "")).upper(): row
        for row in diagnostics.get("rows", [])
        if isinstance(row, Mapping)
    }
    symbols = []
    for row in updated.get("symbols", []):
        if not isinstance(row, Mapping):
            symbols.append(row)
            continue
        item = dict(row)
        diag = rows_by_symbol.get(str(item.get("symbol", "")).upper())
        if diag:
            item.update(
                {
                    "bid": diag.get("bid"),
                    "ask": diag.get("ask"),
                    "last": diag.get("last"),
                    "market_price": diag.get("last") or item.get("market_price"),
                    "bid_age_sec": diag.get("bid_age_sec"),
                    "ask_age_sec": diag.get("ask_age_sec"),
                    "last_age_sec": diag.get("last_age_sec"),
                    "quote_age_sec": min([age for age in [diag.get("bid_age_sec"), diag.get("ask_age_sec"), diag.get("last_age_sec")] if age is not None], default=None),
                    "quote_age_ms": None,
                    "quote_source": "ibkr_streaming",
                    "quote_session": "account_state_streaming",
                    "market_data_type": diag.get("market_data_type"),
                    "market_data_type_name": diag.get("market_data_type_name"),
                    "snapshot_request_used": False,
                    "regulatory_snapshot_used": False,
                    "paid_snapshot_risk": False,
                    "stale_quote_warning": bool(diag.get("blocked_reason")),
                    "streaming_blocked_reason": diag.get("blocked_reason"),
                }
            )
        symbols.append(item)
    updated["symbols"] = symbols
    updated["streaming_quote_diagnostics_path"] = str(STREAMING_QUOTE_DIAGNOSTICS_DIR / "latest.json")
    return updated


def symbols_from_guard(guard: Mapping[str, Any]) -> list[str]:
    symbols = {
        str(row.get("symbol", "")).upper()
        for row in guard.get("symbols", [])
        if isinstance(row, Mapping) and row.get("symbol")
    }
    return sorted(symbols)


def require_fresh_state_for_execution(state: AccountState | None = None, *, settings: Settings | None = None) -> ForceRefreshResult:
    refreshed = build_account_state(settings=settings, force_refresh=True, write_reports_enabled=True) if state is None else state
    result = refreshed.force_refresh or ForceRefreshResult(True, False, False, False, False, False, False, False, "force refresh result missing")
    if not result.force_refresh_ok:
        return result
    if refreshed.state_stale:
        return ForceRefreshResult(True, result.force_refresh_performed, False, result.positions_refreshed, result.open_orders_refreshed, result.quotes_refreshed, result.pnl_refreshed, result.protection_coverage_refreshed, refreshed.blocked_reason or "account state is stale")
    return result


def build_quote_states(rows: Any, *, now: str) -> list[QuoteState]:
    states: list[QuoteState] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        for use_case in QUOTE_USE_CASES:
            states.append(quote_state_from_guard(row, now=now, use_case=use_case))
    return states


def quote_state_from_guard(row: Mapping[str, Any], *, now: str, use_case: str) -> QuoteState:
    symbol = str(row.get("symbol", "")).upper()
    bid = float_or_none(row.get("bid"))
    ask = float_or_none(row.get("ask"))
    last = float_or_none(row.get("last") or row.get("market_price"))
    bid_age = quote_age_sec(row, "bid")
    ask_age = quote_age_sec(row, "ask")
    last_age = quote_age_sec(row, "last")
    threshold = quote_threshold(use_case)
    market_data_type = parse_market_data_type(row)
    market_data_type_name = market_data_type_label(market_data_type)
    delayed = market_data_type in {3, 4}
    frozen = market_data_type in {2, 4}
    snapshot_used = bool(row.get("snapshot_request_used") or row.get("snapshot_used"))
    regulatory_used = bool(row.get("regulatory_snapshot_used"))
    paid_risk = bool(regulatory_used or (snapshot_used and not env_bool("ALLOW_SNAPSHOT_MARKET_DATA", False)))
    actual = actual_quote_age_for_use_case(use_case=use_case, bid_age=bid_age, ask_age=ask_age, last_age=last_age)
    available = bid is not None or ask is not None or last is not None
    stale_reason = quote_stale_reason(
        use_case=use_case,
        bid=bid,
        ask=ask,
        last=last,
        bid_age=bid_age,
        ask_age=ask_age,
        last_age=last_age,
        threshold=threshold,
    )
    execution_case = use_case in {"EXECUTION_GATE", "GAP_ESCAPE"}
    live_confirmed = market_data_type == 1
    blocked_reason = quote_blocked_reason(
        stale_reason=stale_reason,
        execution_case=execution_case,
        live_confirmed=live_confirmed,
        delayed=delayed,
        frozen=frozen,
        snapshot_used=snapshot_used,
        regulatory_used=regulatory_used,
        paid_risk=paid_risk,
    )
    return QuoteState(
        timestamp=now,
        symbol=symbol,
        bid=bid,
        ask=ask,
        last=last,
        bid_age_sec=bid_age,
        ask_age_sec=ask_age,
        last_age_sec=last_age,
        spread_pct=spread(bid, ask, last or bid or ask),
        quote_available=available,
        quote_source=str(row.get("quote_source") or "position_guard"),
        quote_session=str(row.get("quote_session") or infer_quote_session()),
        quote_use_case=use_case,
        market_data_type=market_data_type,
        market_data_type_name=market_data_type_name,
        live_data_confirmed=live_confirmed,
        delayed_data_detected=delayed,
        frozen_data_detected=frozen,
        snapshot_request_used=snapshot_used,
        regulatory_snapshot_used=regulatory_used,
        paid_snapshot_risk=paid_risk,
        execution_allowed_from_quote=execution_case and not blocked_reason,
        blocked_reason=blocked_reason,
        threshold_used_sec=threshold,
        actual_age_sec=actual,
        stale_reason=stale_reason,
        quote_stale=bool(stale_reason),
        execution_blocked_due_to_stale_quote=execution_case and bool(blocked_reason),
    )


def quote_execution_readiness(row: Mapping[str, Any], *, side: str, use_case: str = "EXECUTION_GATE") -> dict[str, Any]:
    side = side.upper()
    threshold = quote_threshold(use_case)
    bid = float_or_none(row.get("bid"))
    ask = float_or_none(row.get("ask"))
    bid_age = quote_age_sec(row, "bid")
    ask_age = quote_age_sec(row, "ask")
    market_data_type = parse_market_data_type(row)
    if env_bool("MARKET_DATA_EXECUTION_REQUIRES_LIVE", True) and market_data_type != 1:
        return {"ok": False, "blocked_reason": f"{row.get('symbol')}: execution blocked because market_data_type={market_data_type_label(market_data_type)} is not live"}
    if market_data_type in {2, 3, 4} and not env_bool("ALLOW_DELAYED_DATA_FOR_EXECUTION", False):
        return {"ok": False, "blocked_reason": f"{row.get('symbol')}: execution blocked because delayed/frozen market data cannot be used"}
    if row.get("snapshot_request_used") or row.get("regulatory_snapshot_used"):
        return {"ok": False, "blocked_reason": f"{row.get('symbol')}: execution blocked because snapshot/regulatory snapshot data was used"}
    if side == "SELL":
        if bid is None:
            return {"ok": False, "blocked_reason": f"{row.get('symbol')}: SELL execution blocked because bid is missing"}
        if bid_age is None:
            return {"ok": False, "blocked_reason": f"{row.get('symbol')}: SELL execution blocked because bid_age_sec is missing"}
        if bid_age > threshold:
            return {"ok": False, "blocked_reason": f"{row.get('symbol')}: SELL execution blocked because bid_age_sec={round(bid_age, 3)} exceeds {threshold}"}
        return {"ok": True, "blocked_reason": ""}
    if side == "BUY":
        if ask is None:
            return {"ok": False, "blocked_reason": f"{row.get('symbol')}: BUY execution blocked because ask is missing"}
        if ask_age is None:
            return {"ok": False, "blocked_reason": f"{row.get('symbol')}: BUY execution blocked because ask_age_sec is missing"}
        if ask_age > threshold:
            return {"ok": False, "blocked_reason": f"{row.get('symbol')}: BUY execution blocked because ask_age_sec={round(ask_age, 3)} exceeds {threshold}"}
        return {"ok": True, "blocked_reason": ""}
    return {"ok": False, "blocked_reason": f"unsupported execution side: {side}"}


def quote_stale_reason(
    *,
    use_case: str,
    bid: float | None,
    ask: float | None,
    last: float | None,
    bid_age: float | None,
    ask_age: float | None,
    last_age: float | None,
    threshold: float,
) -> str:
    if use_case == "DASHBOARD":
        if last is not None and last_age is not None and last_age <= threshold:
            return ""
        if bid is not None and bid_age is not None and bid_age <= threshold:
            return ""
        if ask is not None and ask_age is not None and ask_age <= threshold:
            return ""
        return "dashboard quote stale or missing; last/bid/ask fallback unavailable within threshold"
    if use_case == "MONITORING":
        if (bid is not None and bid_age is not None and bid_age <= threshold) or (ask is not None and ask_age is not None and ask_age <= threshold) or (last is not None and last_age is not None and last_age <= threshold):
            return ""
        return "monitoring quote stale or missing"
    if use_case == "PROTECTION_PLANNING":
        if bid is None or bid_age is None:
            return "protection planning requires bid freshness for SELL stop planning"
        if bid_age > threshold:
            return f"protection planning bid stale: bid_age_sec={round(bid_age, 3)} threshold={threshold}"
        return ""
    if use_case in {"EXECUTION_GATE", "GAP_ESCAPE"}:
        if bid is None or bid_age is None:
            return f"{use_case} blocks SELL execution because bid is missing or has no age"
        if bid_age > threshold:
            return f"{use_case} blocks SELL execution because bid_age_sec={round(bid_age, 3)} threshold={threshold}"
        return ""
    return f"unknown quote use case: {use_case}"


def actual_quote_age_for_use_case(*, use_case: str, bid_age: float | None, ask_age: float | None, last_age: float | None) -> float | None:
    if use_case in {"PROTECTION_PLANNING", "EXECUTION_GATE", "GAP_ESCAPE"}:
        return bid_age
    ages = [age for age in [bid_age, ask_age, last_age] if age is not None]
    return min(ages) if ages else None


def quote_age_sec(row: Mapping[str, Any], field: str) -> float | None:
    specific = float_or_none(row.get(f"{field}_age_sec"))
    if specific is not None:
        return specific
    specific_ms = float_or_none(row.get(f"{field}_age_ms"))
    if specific_ms is not None:
        return specific_ms / 1000.0
    age_ms = float_or_none(row.get("quote_age_ms"))
    if age_ms is not None:
        return age_ms / 1000.0
    age_sec = float_or_none(row.get("quote_age_sec"))
    if age_sec is not None:
        return age_sec
    return None


def quote_threshold(use_case: str) -> float:
    return QUOTE_FRESHNESS_THRESHOLDS_SEC.get(use_case.upper(), DEFAULT_QUOTE_STALE_SEC)


def parse_market_data_type(row: Mapping[str, Any]) -> int | None:
    raw = row.get("market_data_type")
    if raw in (None, ""):
        return None
    if isinstance(raw, int):
        return raw
    text = str(raw).strip().lower()
    reverse = {"live": 1, "frozen": 2, "delayed": 3, "delayed_frozen": 4, "delayed frozen": 4}
    if text in reverse:
        return reverse[text]
    try:
        return int(text)
    except ValueError:
        return None


def market_data_type_label(value: int | None) -> str:
    return MARKET_DATA_TYPE_NAMES.get(value, "unknown")


def quote_blocked_reason(
    *,
    stale_reason: str,
    execution_case: bool,
    live_confirmed: bool,
    delayed: bool,
    frozen: bool,
    snapshot_used: bool,
    regulatory_used: bool,
    paid_risk: bool,
) -> str:
    reasons = []
    if stale_reason:
        reasons.append(stale_reason)
    if execution_case and env_bool("MARKET_DATA_EXECUTION_REQUIRES_LIVE", True) and not live_confirmed:
        reasons.append("execution requires live market data")
    if execution_case and delayed and not env_bool("ALLOW_DELAYED_DATA_FOR_EXECUTION", False):
        reasons.append("delayed data cannot pass execution readiness")
    if execution_case and frozen:
        reasons.append("frozen data cannot pass execution readiness")
    if execution_case and snapshot_used:
        reasons.append("snapshot data cannot pass execution readiness")
    if execution_case and regulatory_used:
        reasons.append("regulatory snapshot data cannot pass execution readiness")
    if paid_risk:
        reasons.append("paid snapshot risk detected")
    return "; ".join(dict.fromkeys(reasons))


def position_state_from_guard(row: Mapping[str, Any], *, now: str, freshness: StateFreshness) -> PositionState:
    qty = float(row.get("position_qty") or 0)
    avg_cost = float_or_none(row.get("avg_cost"))
    market_price = float_or_none(row.get("market_price") or row.get("last"))
    unrealized = float_or_none(row.get("unrealized_pnl"))
    spread_pct = spread(row.get("bid"), row.get("ask"), market_price)
    return PositionState(
        timestamp=now,
        symbol=str(row.get("symbol", "")).upper(),
        quantity=qty,
        avg_cost=avg_cost,
        market_price=market_price,
        bid=float_or_none(row.get("bid")),
        ask=float_or_none(row.get("ask")),
        last=float_or_none(row.get("last")),
        market_value=float_or_none(row.get("market_value")),
        unrealized_pnl=unrealized,
        unrealized_pnl_pct=(unrealized / abs(avg_cost * qty)) if unrealized is not None and avg_cost and qty else None,
        quote_stale=bool(row.get("stale_quote_warning")),
        spread_pct=spread_pct,
        pnl_age_sec=freshness.pnl_age_sec,
        position_age_sec=freshness.positions_age_sec,
    )


def open_order_state(row: Mapping[str, Any], *, now: str, age: float | None) -> OpenOrderState:
    status = row.get("order_status") if isinstance(row.get("order_status"), Mapping) else {}
    return OpenOrderState(
        timestamp=now,
        symbol=str(row.get("symbol", "")).upper(),
        side=str(row.get("action") or row.get("side") or "").upper(),
        order_type=str(row.get("order_type") or ""),
        quantity=float(row.get("total_quantity") or row.get("quantity") or 0),
        remaining=float_or_none(status.get("remaining") if isinstance(status, Mapping) else row.get("remaining")),
        limit_price=float_or_none(row.get("limit_price")),
        stop_price=float_or_none(row.get("aux_price") or row.get("stop_price")),
        outsideRth_requested=row.get("outsideRth_requested"),
        outsideRth_effective=row.get("outside_rth"),
        status=str(row.get("status") or status.get("status") or ""),
        ib_order_id=int(row["order_id"]) if row.get("order_id") not in (None, "") else None,
        open_order_age_sec=age,
    )


def coverage_state(row: Mapping[str, Any], *, now: str, age: float | None) -> ProtectionCoverageState:
    qty = float(row.get("position_qty") or 0)
    stop_qty = float(row.get("protective_stop_qty") or 0)
    return ProtectionCoverageState(
        timestamp=now,
        symbol=str(row.get("symbol", "")).upper(),
        position_qty=qty,
        existing_stop_qty=stop_qty,
        uncovered_qty=max(0.0, qty - stop_qty),
        covered=bool(row.get("position_covered_by_stop")),
        overprotected=bool(row.get("overprotected_warning")),
        duplicate_stop_risk=bool(row.get("duplicate_stop_warning")),
        protection_coverage_age_sec=age,
    )


def build_pnl_states(*, account: Mapping[str, Any], latest_pnl: Mapping[str, Any], positions: list[PositionState], now: str, pnl_age_sec: float | None) -> list[PnLState]:
    support = pnl_subscription_support()
    fallback_used = not support["symbol_level_pnl_available"]
    fallback_reason = "" if not fallback_used else "symbol-level reqPnLSingle is not wired; using portfolio/updatePortfolio/account report fields"
    states = [
        PnLState(
            timestamp=now,
            account_id=str(account.get("account") or latest_pnl.get("account") or ""),
            symbol=None,
            daily_pnl=float_or_none(account.get("daily_pnl") or latest_pnl.get("daily_pnl")),
            realized_pnl=float_or_none(account.get("realized_pnl") or latest_pnl.get("realized_pnl")),
            unrealized_pnl=float_or_none(account.get("unrealized_pnl") or latest_pnl.get("unrealized_pnl")),
            pnl_age_sec=pnl_age_sec,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            **support,
        )
    ]
    for position in positions:
        states.append(
            PnLState(
                timestamp=now,
                account_id=str(account.get("account") or latest_pnl.get("account") or ""),
                symbol=position.symbol,
                daily_pnl=None,
                realized_pnl=None,
                unrealized_pnl=position.unrealized_pnl,
                pnl_age_sec=pnl_age_sec,
                fallback_used=True,
                fallback_reason="symbol PnL derived from position_guard/updatePortfolio fallback",
                **support,
            )
        )
    return states


def pnl_subscription_support() -> dict[str, bool]:
    try:
        from scripts.record_account_pnl import AccountPnlClient
    except Exception:
        return {
            "pnl_subscription_available": False,
            "account_level_pnl_available": False,
            "symbol_level_pnl_available": False,
            "req_pnl_available": False,
            "req_pnl_single_available": False,
        }
    return {
        "pnl_subscription_available": True,
        "account_level_pnl_available": hasattr(AccountPnlClient, "pnl"),
        "symbol_level_pnl_available": False,
        "req_pnl_available": True,
        "req_pnl_single_available": False,
    }


def build_freshness(*, account_path: Path, positions_path: Path, open_orders_path: Path, pnl_path: Path, protection_path: Path, position_rows: Any) -> StateFreshness:
    quote_ages = [
        quote_age_for_freshness(row)
        for row in position_rows
        if isinstance(row, Mapping) and quote_age_for_freshness(row) is not None
    ]
    return StateFreshness(
        account_summary_age_sec=file_age(account_path),
        positions_age_sec=file_age(positions_path),
        open_orders_age_sec=file_age(open_orders_path),
        quotes_age_sec=max(quote_ages) if quote_ages else None,
        pnl_age_sec=file_age(pnl_path),
        protection_coverage_age_sec=file_age(protection_path),
    )


def stale_status(freshness: StateFreshness) -> tuple[bool, str]:
    checks = {
        "account summary": (freshness.account_summary_age_sec, DEFAULT_STALE_SEC * 10),
        "positions": (freshness.positions_age_sec, DEFAULT_STALE_SEC * 2),
        "open orders": (freshness.open_orders_age_sec, DEFAULT_STALE_SEC * 2),
        "quotes": (freshness.quotes_age_sec, DEFAULT_QUOTE_STALE_SEC),
        "PnL": (freshness.pnl_age_sec, DEFAULT_STALE_SEC * 10),
        "protection coverage": (freshness.protection_coverage_age_sec, DEFAULT_STALE_SEC * 2),
    }
    stale = []
    for name, (age, limit) in checks.items():
        if age is None:
            stale.append(f"{name} missing")
        elif age > limit:
            stale.append(f"{name} stale age_sec={round(age, 3)} limit={limit}")
    return bool(stale), "; ".join(stale)


def write_account_state_reports(state: AccountState) -> None:
    payload = account_state_payload(state)
    write_json_report(ACCOUNT_STATE_DIR, payload, markdown=account_state_md(payload))
    write_json_report(POSITION_STATE_DIR, {"timestamp": state.timestamp, "source": "position_state", "positions": [asdict(item) for item in state.positions]})
    open_age = None if state.freshness is None else state.freshness.open_orders_age_sec
    open_order_payload = {
        "timestamp": state.timestamp,
        "source": "open_order_state",
        "open_orders_refresh_requested": True,
        "open_orders_refresh_ok": open_age is not None and open_age <= DEFAULT_STALE_SEC * 2,
        "open_orders_count": len(state.open_orders),
        "open_orders_age_sec": open_age,
        "open_orders_stale": open_age is None or open_age > DEFAULT_STALE_SEC * 2,
        "blocked_reason": "open orders stale or missing" if open_age is None or open_age > DEFAULT_STALE_SEC * 2 else "",
        "open_orders": [asdict(item) for item in state.open_orders],
    }
    write_json_report(OPEN_ORDER_STATE_DIR, open_order_payload, markdown=open_order_state_md(open_order_payload))
    quote_payload = {"timestamp": state.timestamp, "source": "quote_state", "thresholds_sec": QUOTE_FRESHNESS_THRESHOLDS_SEC, "quotes": [asdict(item) for item in state.quotes]}
    write_json_report(QUOTE_STATE_DIR, quote_payload, markdown=quote_state_md(quote_payload))
    pnl_payload = {"timestamp": state.timestamp, "source": "pnl_state", "pnl": [asdict(item) for item in state.pnl], **pnl_subscription_support()}
    write_json_report(PNL_STATE_DIR, pnl_payload, markdown=pnl_state_md(pnl_payload))
    dashboard = account_dashboard_payload(state)
    write_json_report(ACCOUNT_DASHBOARD_DIR, dashboard, markdown=account_dashboard_md(dashboard))
    monitoring = monitoring_line_payload(state)
    write_json_report(MONITORING_LINE_DIR, monitoring, markdown=monitoring_line_md(monitoring))
    readiness = account_execution_readiness_payload(state)
    write_json_report(ACCOUNT_EXECUTION_READINESS_DIR, readiness, markdown=account_execution_readiness_md(readiness))


def account_state_payload(state: AccountState) -> dict[str, Any]:
    payload = asdict(state)
    payload["source"] = "account_state_manager"
    payload["report_only"] = True
    payload["orders_submitted"] = 0
    payload["orders_cancelled"] = 0
    return payload


def account_dashboard_payload(state: AccountState) -> dict[str, Any]:
    symbols_held = [item.symbol for item in state.positions if item.quantity != 0]
    covered = [item.symbol for item in state.protection_coverage if item.covered or item.existing_stop_qty > 0]
    missing = [item.symbol for item in state.protection_coverage if item.uncovered_qty > 0]
    freshness = asdict(state.freshness) if state.freshness else {}
    warnings = []
    if state.state_stale:
        warnings.append(state.blocked_reason)
    dashboard_quotes = [item for item in state.quotes if item.quote_use_case == "DASHBOARD"]
    if any(item.quote_stale for item in dashboard_quotes):
        warnings.append("one or more dashboard quotes are stale")
    return {
        "timestamp": state.timestamp,
        "source": "account_dashboard",
        "mode": state.mode,
        "net_liquidation": state.net_liquidation,
        "cash": state.cash,
        "buying_power": state.buying_power,
        "gross_position_value": state.gross_position_value,
        "realized_pnl": state.realized_pnl,
        "unrealized_pnl": state.unrealized_pnl,
        "number_of_positions": len(state.positions),
        "number_of_open_orders": len(state.open_orders),
        "symbols_held": symbols_held,
        "symbols_with_protection": covered,
        "symbols_missing_protection": missing,
        "quotes_age_sec": freshness.get("quotes_age_sec"),
        "positions_age_sec": freshness.get("positions_age_sec"),
        "open_orders_age_sec": freshness.get("open_orders_age_sec"),
        "pnl_age_sec": freshness.get("pnl_age_sec"),
        "protection_coverage_age_sec": freshness.get("protection_coverage_age_sec"),
        "state_stale": state.state_stale,
        "buy_freeze_active": env_bool("MODE9_BUY_FREEZE", True),
        "live_trading_enabled": env_bool("LIVE_TRADING_ENABLED", False),
        "paper_only": state.mode in {"PAPER", "DRY_RUN"} and not env_bool("LIVE_TRADING_ENABLED", False),
        "warnings": [item for item in warnings if item],
    }


def account_execution_readiness_payload(state: AccountState) -> dict[str, Any]:
    execution_quotes = [item for item in state.quotes if item.quote_use_case == "EXECUTION_GATE"]
    quote_blocks = [item.blocked_reason for item in execution_quotes if item.blocked_reason]
    freshness = state.freshness
    positions_ready = freshness is not None and freshness.positions_age_sec is not None and freshness.positions_age_sec <= DEFAULT_STALE_SEC * 2
    open_orders_ready = freshness is not None and freshness.open_orders_age_sec is not None and freshness.open_orders_age_sec <= DEFAULT_STALE_SEC * 2
    pnl_ready = freshness is not None and freshness.pnl_age_sec is not None and freshness.pnl_age_sec <= DEFAULT_STALE_SEC * 10
    protection_ready = freshness is not None and freshness.protection_coverage_age_sec is not None and freshness.protection_coverage_age_sec <= DEFAULT_STALE_SEC * 2
    paid_snapshot_used = any(item.paid_snapshot_risk or item.snapshot_request_used for item in execution_quotes)
    regulatory_used = any(item.regulatory_snapshot_used for item in execution_quotes)
    delayed_execution = any(item.delayed_data_detected or item.frozen_data_detected for item in execution_quotes)
    live_confirmed = bool(execution_quotes) and all(item.live_data_confirmed for item in execution_quotes)
    quotes_ready = bool(execution_quotes) and not quote_blocks and live_confirmed
    blocking = []
    if not quotes_ready:
        blocking.extend(quote_blocks or ["execution quotes missing or not live-confirmed"])
    if not positions_ready:
        blocking.append("positions stale or missing")
    if not open_orders_ready:
        blocking.append("open orders stale or missing")
    if not pnl_ready:
        blocking.append("PnL stale or missing")
    if not protection_ready:
        blocking.append("protection coverage stale or missing")
    if paid_snapshot_used:
        blocking.append("paid snapshot risk exists")
    if regulatory_used:
        blocking.append("regulatory snapshot used")
    if delayed_execution:
        blocking.append("delayed/frozen data used for execution")
    return {
        "timestamp": state.timestamp,
        "source": "account_execution_readiness",
        "account_execution_ready": not blocking,
        "quotes_ready": quotes_ready,
        "positions_ready": positions_ready,
        "open_orders_ready": open_orders_ready,
        "pnl_ready": pnl_ready,
        "protection_coverage_ready": protection_ready,
        "live_quote_required": env_bool("MARKET_DATA_EXECUTION_REQUIRES_LIVE", True),
        "live_quote_confirmed": live_confirmed,
        "delayed_data_used_for_execution": delayed_execution,
        "paid_snapshot_used": paid_snapshot_used,
        "regulatory_snapshot_used": regulatory_used,
        "blocking_reasons": list(dict.fromkeys(reason for reason in blocking if reason)),
    }


def monitoring_line_payload(state: AccountState) -> dict[str, Any]:
    return {
        "timestamp": state.timestamp,
        "source": "monitoring_line",
        "mode9_monitoring_line_enabled": env_bool("MODE9_MONITORING_LINE_ENABLED", True),
        "account_state_manager_enabled": env_bool("ACCOUNT_STATE_MANAGER_ENABLED", True),
        "account_state_manager_connected_to_mode9": env_bool("ACCOUNT_STATE_MANAGER_CONNECTED_TO_MODE9", True),
        "pool_manager_connected_to_mode9": env_bool("POOL_MANAGER_CONNECTED_TO_MODE9", True),
        "pool_manager_report_only": env_bool("POOL_MANAGER_REPORT_ONLY", True),
        "event_router_report_only": env_bool("EVENT_ROUTER_REPORT_ONLY", True),
        "six_layer_pools_execution_active": env_bool("SIX_LAYER_POOLS_EXECUTION_ACTIVE", False),
        "trade_pool_buy_execution_enabled": env_bool("TRADE_POOL_BUY_EXECUTION_ENABLED", False),
        "mode9_buy_freeze": env_bool("MODE9_BUY_FREEZE", True),
        "live_trading_enabled": env_bool("LIVE_TRADING_ENABLED", False),
        "allow_options_execution": env_bool("ALLOW_OPTIONS_EXECUTION", False),
        "allow_market_orders": env_bool("ALLOW_MARKET_ORDERS", False),
        "state_stale": state.state_stale,
        "blocked_reason": state.blocked_reason,
        "orders_submitted": 0,
    }


def write_json_report(directory: Path, payload: Mapping[str, Any], *, markdown: str | None = None) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "latest.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    if markdown is not None:
        (directory / "latest.md").write_text(markdown, encoding="utf-8")


def write_streaming_quote_diagnostics(payload: Mapping[str, Any]) -> None:
    STREAMING_QUOTE_DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
    (STREAMING_QUOTE_DIAGNOSTICS_DIR / "latest.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    (STREAMING_QUOTE_DIAGNOSTICS_DIR / "latest.md").write_text(streaming_quote_diagnostics_md(payload), encoding="utf-8")


def account_state_md(payload: Mapping[str, Any]) -> str:
    return "\n".join([
        "# Account State",
        "",
        f"- mode: {payload.get('mode')}",
        f"- account_id: {payload.get('account_id')}",
        f"- state_stale: {payload.get('state_stale')}",
        f"- blocked_reason: {payload.get('blocked_reason')}",
        f"- positions: {len(payload.get('positions', []))}",
        f"- open_orders: {len(payload.get('open_orders', []))}",
        f"- used_cached_state: {payload.get('used_cached_state')}",
        f"- force_refresh_ok: {(payload.get('force_refresh') or {}).get('force_refresh_ok')}",
    ]) + "\n"


def pnl_state_md(payload: Mapping[str, Any]) -> str:
    lines = ["# PnL State", "", f"- pnl_subscription_available: {payload.get('pnl_subscription_available')}", f"- req_pnl_available: {payload.get('req_pnl_available')}", f"- req_pnl_single_available: {payload.get('req_pnl_single_available')}", "", "| Symbol | Unrealized | Realized | Fallback | Reason |", "|---|---:|---:|---:|---|"]
    for row in payload.get("pnl", []):
        lines.append(f"| {row.get('symbol') or 'ACCOUNT'} | {row.get('unrealized_pnl')} | {row.get('realized_pnl')} | {row.get('fallback_used')} | {row.get('fallback_reason')} |")
    return "\n".join(lines) + "\n"


def quote_state_md(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Quote State",
        "",
        "Subscription status is not execution readiness. Execution gates require fresh bid/ask updates, not merely an open data pipe.",
        "",
        "| Symbol | Use Case | Bid | Ask | Last | Data Type | Threshold | Actual Age | Blocked Reason | Execution Blocked |",
        "|---|---|---:|---:|---:|---|---:|---:|---|---:|",
    ]
    for row in payload.get("quotes", []):
        lines.append(
            f"| {row.get('symbol')} | {row.get('quote_use_case')} | {row.get('bid')} | {row.get('ask')} | {row.get('last')} | "
            f"{row.get('market_data_type_name')} | {row.get('threshold_used_sec')} | {row.get('actual_age_sec')} | {row.get('blocked_reason')} | {row.get('execution_blocked_due_to_stale_quote')} |"
        )
    return "\n".join(lines) + "\n"


def open_order_state_md(payload: Mapping[str, Any]) -> str:
    lines = ["# Open Order State", "", "| Symbol | Side | Type | Qty | Remaining | Status | Order ID |", "|---|---|---|---:|---:|---|---:|"]
    for row in payload.get("open_orders", []):
        lines.append(f"| {row.get('symbol')} | {row.get('side')} | {row.get('order_type')} | {row.get('quantity')} | {row.get('remaining')} | {row.get('status')} | {row.get('ib_order_id')} |")
    return "\n".join(lines) + "\n"


def account_execution_readiness_md(payload: Mapping[str, Any]) -> str:
    lines = ["# Account Execution Readiness", ""]
    for key in ["account_execution_ready", "quotes_ready", "positions_ready", "open_orders_ready", "pnl_ready", "protection_coverage_ready", "live_quote_required", "live_quote_confirmed", "delayed_data_used_for_execution", "paid_snapshot_used", "regulatory_snapshot_used"]:
        lines.append(f"- {key}: {payload.get(key)}")
    lines.append(f"- blocking_reasons: {payload.get('blocking_reasons')}")
    return "\n".join(lines) + "\n"


def force_refresh_dry_run_md(payload: Mapping[str, Any]) -> str:
    lines = ["# Force Refresh Dry Run", ""]
    for key in ["force_refresh_performed", "force_refresh_ok", "positions_refreshed", "open_orders_refreshed", "quotes_refreshed", "pnl_refreshed", "protection_coverage_refreshed", "state_stale_after_refresh", "execution_ready_after_refresh", "blocked_reason", "paid_market_data_request_used", "regulatory_snapshot_used", "orders_submitted", "orders_cancelled"]:
        lines.append(f"- {key}: {payload.get(key)}")
    return "\n".join(lines) + "\n"


def streaming_quote_diagnostics_md(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Streaming Quote Diagnostics",
        "",
        f"- streaming_request_started: {payload.get('streaming_request_started')}",
        f"- snapshot_request_used: {payload.get('snapshot_request_used')}",
        f"- regulatory_snapshot_used: {payload.get('regulatory_snapshot_used')}",
        f"- paid_snapshot_risk: {payload.get('paid_snapshot_risk')}",
        "",
        "| Symbol | Requested | OK | Type | Live | Bid | Ask | Last | Bid Age | Ask Age | Last Age | Blocked |",
        "|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in payload.get("rows", []):
        lines.append(
            f"| {row.get('symbol')} | {row.get('streaming_requested')} | {row.get('streaming_request_ok')} | "
            f"{row.get('market_data_type_name')} | {row.get('live_data_confirmed')} | {row.get('bid')} | "
            f"{row.get('ask')} | {row.get('last')} | {row.get('bid_age_sec')} | {row.get('ask_age_sec')} | "
            f"{row.get('last_age_sec')} | {row.get('blocked_reason')} |"
        )
    return "\n".join(lines) + "\n"


def account_dashboard_md(payload: Mapping[str, Any]) -> str:
    lines = ["# Account Dashboard", "", f"- mode: {payload.get('mode')}", f"- net_liquidation: {payload.get('net_liquidation')}", f"- cash: {payload.get('cash')}", f"- buying_power: {payload.get('buying_power')}", f"- positions: {payload.get('number_of_positions')}", f"- open_orders: {payload.get('number_of_open_orders')}", f"- state_stale: {payload.get('state_stale')}", f"- warnings: {payload.get('warnings')}"]
    return "\n".join(lines) + "\n"


def monitoring_line_md(payload: Mapping[str, Any]) -> str:
    lines = ["# Monitoring Line", ""]
    for key in ["mode9_monitoring_line_enabled", "account_state_manager_enabled", "account_state_manager_connected_to_mode9", "pool_manager_report_only", "event_router_report_only", "six_layer_pools_execution_active", "trade_pool_buy_execution_enabled", "mode9_buy_freeze", "live_trading_enabled", "allow_options_execution", "allow_market_orders", "orders_submitted"]:
        lines.append(f"- {key}: {payload.get(key)}")
    return "\n".join(lines) + "\n"


def latest_pnl_row() -> dict[str, Any]:
    path = PROJECT_ROOT / "reports" / "pnl_timeseries.csv"
    if not path.exists():
        return {}
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        return dict(rows[-1]) if rows else {}
    except Exception:
        return {}


def file_age(path: Path) -> float | None:
    if not path.exists():
        return None
    return max(0.0, datetime.now(timezone.utc).timestamp() - path.stat().st_mtime)


def quote_age_for_freshness(row: Mapping[str, Any]) -> float | None:
    if row.get("quote_age_sec") not in (None, ""):
        return float_or_none(row.get("quote_age_sec"))
    if row.get("quote_age_ms") not in (None, ""):
        value = float_or_none(row.get("quote_age_ms"))
        return None if value is None else value / 1000.0
    ages = [quote_age_sec(row, field) for field in ("bid", "ask", "last")]
    available = [age for age in ages if age is not None]
    return min(available) if available else None


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def float_or_none(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def sum_float(values: Any) -> float | None:
    total = 0.0
    found = False
    for value in values:
        if value is None:
            continue
        total += float(value)
        found = True
    return total if found else None


def spread(bid: Any, ask: Any, reference: float | None) -> float | None:
    bid_f = float_or_none(bid)
    ask_f = float_or_none(ask)
    if bid_f is None or ask_f is None or reference is None or reference <= 0 or ask_f < bid_f:
        return None
    return (ask_f - bid_f) / reference


def infer_quote_session() -> str:
    return os.getenv("QUOTE_SESSION", "unknown")


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
