import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from trading.config import PROJECT_ROOT, Settings
from trading.account_state_manager import require_fresh_state_for_execution
from trading.market_data import Quote
from trading.position_guard import build_position_guard_report
from trading.price_normalizer import DEFAULT_US_STOCK_MIN_TICK, normalize_order_price
from trading.process_guard import read_lock
from trading.tws_paper import TwsPaperBroker


REPORT_DIR = PROJECT_ROOT / "reports" / "position_protection"
ACTIVE_ORDER_STATUSES = {"Submitted", "PreSubmitted", "Accepted", "ApiPending", "PendingSubmit"}

# STRATEGY_DEBT[STOP-001]:
# Temporary fallback value.
# Reason: dynamic ATR/cost/regime model is not fully validated yet.
# Future: replace or tune with backtest and live paper evidence.
DEFAULT_STOP_PCT = 0.05

# STRATEGY_DEBT[STOP-002]:
# Temporary min stop boundary.
# Reason: minimum stop distance has not been calibrated by symbol volatility buckets.
# Future: replace or tune with backtest and live paper evidence.
MIN_STOP_PCT = 0.03

# STRATEGY_DEBT[STOP-003]:
# Temporary max stop boundary.
# Reason: maximum stop distance has not been calibrated by drawdown and capital-at-risk studies.
# Future: replace or tune with backtest and live paper evidence.
MAX_STOP_PCT = 0.12

# STRATEGY_DEBT[STOP-004]:
# Temporary ATR multiplier.
# Reason: ATR-based stop widening has not been validated by regime and holding-period tests.
# Future: replace or tune with backtest and live paper evidence.
ATR_MULTIPLIER = 1.5

# STRATEGY_DEBT[STOP-005]:
# Temporary spread multiplier.
# Reason: spread-based stop widening is a conservative paper-trading heuristic.
# Future: replace or tune with backtest and live paper evidence.
SPREAD_MULTIPLIER = 3.0

# STRATEGY_DEBT[STOP-006]:
# Temporary quote freshness threshold.
# Reason: quote age tolerance has not been tuned per session and liquidity regime.
# Future: replace or tune with backtest and live paper evidence.
STALE_QUOTE_MS = 5_000.0

# STRATEGY_DEBT[STOP-007]:
# Temporary repair per-cycle limit.
# Reason: repair throughput has not been validated under many-position portfolios.
# Future: replace or tune with backtest and live paper evidence.
REPAIR_MAX_PER_CYCLE = 10
STOP_LIMIT_OFFSET_PCT = 0.005

STOP_STRATEGY_DEBT_IDS = [
    "STOP-001",
    "STOP-002",
    "STOP-003",
    "STOP-004",
    "STOP-005",
    "STOP-006",
    "STOP-007",
]


@dataclass(frozen=True)
class ProtectionRepairRecord:
    timestamp: str
    symbol: str
    position_qty: float
    avg_cost: float | None
    market_price: float | None
    uncovered_qty: int
    existing_stop_qty: float
    new_stop_qty: int
    raw_stop_price: float | None
    normalized_stop_price: float | None
    min_tick: float
    stop_pct: float
    stop_policy_reason: str
    submitted_order_id: int | None
    submitted: bool
    blocked_reason: str
    action_taken: str
    side: str
    order_type: str
    tif: str
    outside_rth: bool
    order_ref: str | None
    confirmation_statuses: dict[int, str]
    confirmation_open_order_states: dict[int, str]
    used_cached_state: bool
    force_refresh_required: bool
    force_refresh_performed: bool
    force_refresh_ok: bool
    state_stale: bool


@dataclass(frozen=True)
class RepairPreviewProposal:
    symbol: str
    position_qty: float
    avg_cost: float | None
    stop_mode: str
    average_cost: float | None
    market_price: float | None
    current_price: float | None
    reference_price: float | None
    bid: float | None
    ask: float | None
    last: float | None
    quote_age_sec: float | None
    quote_age_ms: float | None
    open_orders_count_for_symbol: int
    existing_protective_qty: float
    existing_STP_qty: float
    existing_STP_LMT_qty: float
    outsideRth_requested_existing: bool
    outsideRth_effective_existing: bool
    plain_STP_outsideRth_warning: bool
    atr: float | None
    atr_pct: float | None
    spread_pct: float | None
    raw_stop_pct: float | None
    stop_pct: float | None
    min_stop_pct: float
    max_stop_pct: float
    default_stop_pct: float
    existing_stop_qty: float
    uncovered_qty: int
    underprotected_qty: int
    overprotected_qty: float
    duplicate_protection_detected: bool
    recommended_action: str
    recommended_order_type: str
    recommended_qty: int
    raw_limit_price: float | None
    normalized_limit_price: float | None
    outsideRth_requested: bool
    expected_outsideRth_supported: bool
    execution_preview_allowed: bool
    blocked_reason: str
    proposed_action: str
    proposed_order_type: str
    proposed_qty: int
    proposed_stop_price: float | None
    raw_stop_price: float | None
    stop_distance_pct: float | None
    cost_stop_distance_pct: float | None
    estimated_loss_if_triggered: float | None
    estimated_pnl_if_stop_triggered: float | None
    unrealized_pnl_pct: float | None
    would_trigger_immediately: bool
    duplicate_risk: bool
    overprotected_risk: bool
    quote_stale: bool
    manual_review_required: bool
    safe_to_repair: bool
    reason: str
    strategy_debt_ids: list[str]
    existing_stop_details: list[dict[str, Any]]


@dataclass(frozen=True)
class StopConfig:
    mode: str
    default_pct: float
    min_pct: float
    max_pct: float
    atr_multiplier: float
    spread_multiplier: float
    stale_ms: float
    require_fresh_quote: bool
    repair_max_per_cycle: int


@dataclass(frozen=True)
class RepairConfig:
    enabled: bool
    mode: str
    test_symbol: str
    test_order_limit: int
    run_max_orders: int
    run_require_test_success: bool


@dataclass(frozen=True)
class TestThenBulkSelection:
    test_symbol_mode: str
    test_order_limit: int
    eligible_test_symbols: list[dict[str, Any]]
    selected_test_symbol: str | None
    selected_reason: str
    uncovered_qty: int | None
    uncovered_notional: float | None
    existing_stop_qty: float | None
    proposed_stop_price: float | None


def run_position_protection(
    *,
    settings: Settings | None = None,
    enabled: bool | None = None,
    guard_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    settings = settings or Settings.load()
    repair_config = load_repair_config(enabled=enabled)
    stop_config = load_stop_config()
    guard = dict(guard_report or build_position_guard_report(settings=settings))
    preview = build_repair_preview_report(settings=settings, guard_report=guard, stop_config=stop_config, repair_config=repair_config)
    execution_plan = build_repair_execution_plan(settings=settings, preview=preview, repair_config=repair_config)
    allowed_symbols = set(execution_plan["allowed_repair_symbols"])
    rows = []
    preview_by_symbol = {item["symbol"]: item for item in preview["proposals"]}
    for row in guard.get("symbols", []):
        preview_row = preview_by_symbol.get(str(row.get("symbol", "")).upper())
        cycle_enabled = repair_config.enabled and str(row.get("symbol", "")).upper() in allowed_symbols
        record = _repair_record_for_row(
            row,
            settings=settings,
            enabled=cycle_enabled,
            stop_config=stop_config,
            preview=preview_row,
        )
        rows.append(asdict(record))
    submitted_rows = [row for row in rows if row["submitted"]]
    test_result = None
    if repair_config.enabled and repair_config.mode == "test" and submitted_rows:
        test_result = build_test_repair_result(
            submitted_rows[0],
            preview_by_symbol.get(str(submitted_rows[0]["symbol"]).upper()),
            settings=settings,
        )
        write_test_repair_result(test_result)
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "position_protection",
        "enabled": repair_config.enabled,
        "mode": settings.trading_mode,
        "position_protection_repair_enabled": repair_config.enabled,
        "position_protection_repair_mode": repair_config.mode,
        "paper_operation_mode": paper_operation_mode(repair_config),
        "buy_freeze": _bool_env("MODE9_BUY_FREEZE", True),
        "live_enabled": _bool_env("LIVE_TRADING_ENABLED", False),
        "stop_mode": stop_config.mode,
        "stop_pct": stop_config.default_pct,
        "repair_max_per_cycle": stop_config.repair_max_per_cycle,
        "test_then_bulk": preview.get("test_then_bulk"),
        "test_repair_success": bool((test_result or latest_test_repair_result()).get("success")),
        "run_allowed": execution_plan["run_allowed"],
        "run_blocked_reason": execution_plan["run_blocked_reason"],
        "submitted_protection_orders": [row for row in rows if row["submitted"]],
        "repair_preview_path": str(REPORT_DIR / "repair_preview.json"),
        "records": rows,
        "submitted_count": sum(1 for row in rows if row["submitted"]),
    }
    write_report(report)
    return report


def _repair_record_for_row(
    row: Mapping[str, Any],
    *,
    settings: Settings,
    enabled: bool,
    stop_config: StopConfig,
    preview: Mapping[str, Any] | None = None,
) -> ProtectionRepairRecord:
    symbol = str(row.get("symbol", "")).upper()
    position_qty = float(row.get("position_qty") or 0.0)
    existing_stop_qty = float(row.get("protective_stop_qty") or 0.0)
    uncovered = calculate_uncovered_qty(position_qty, existing_stop_qty)
    avg_cost = _float_or_none(row.get("avg_cost"))
    market_price = _float_or_none(row.get("market_price"))
    side = "SELL"
    order_type = "STP"
    tif = "GTC"
    outside_rth = bool(settings.allow_outside_rth)
    if preview is not None:
        raw_stop = _float_or_none(preview.get("raw_stop_price"))
        normalized = _float_or_none(preview.get("proposed_stop_price"))
        policy_reason = str(preview.get("reason") or "repair preview stop")
    else:
        raw_stop, policy_reason = calculate_raw_stop_price(
            avg_cost=avg_cost,
            market_price=market_price,
            stop_pct=stop_config.default_pct,
        )
        normalized = None if raw_stop is None else normalize_order_price(
            symbol=symbol,
            side="SELL",
            order_type="STP",
            price=raw_stop,
        )

    blocked = _blocked_reason(
        row,
        settings=settings,
        enabled=enabled,
        uncovered_qty=uncovered,
        raw_stop_price=raw_stop,
        normalized_stop_price=normalized,
        preview=preview,
    )
    submitted_order_id = None
    submitted = False
    order_ref = None
    confirmation_statuses: dict[int, str] = {}
    confirmation_open_order_states: dict[int, str] = {}
    force_refresh_required = False
    force_refresh_performed = False
    force_refresh_ok = False
    state_stale = True
    action = "blocked" if blocked else "submit_protective_sell_stop"
    if not blocked:
        refresh = require_fresh_state_for_execution(settings=settings)
        force_refresh_required = refresh.force_refresh_required
        force_refresh_performed = refresh.force_refresh_performed
        force_refresh_ok = refresh.force_refresh_ok
        state_stale = not refresh.force_refresh_ok
        if not refresh.force_refresh_ok:
            blocked = refresh.blocked_reason or "account state force refresh failed"
            action = "blocked"
        else:
            state_stale = False
    if not blocked:
        order_ref = f"protect-{symbol.lower()}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"[:64]
        broker = TwsPaperBroker(settings.tws_host, settings.tws_port, settings.tws_client_id + 930)
        confirmation = broker.submit_stop(
            symbol=symbol,
            action="SELL",
            quantity=uncovered,
            stop_price=float(normalized),
            order_ref=order_ref,
            transmit=True,
            outside_rth=outside_rth,
        )
        submitted_order_id = confirmation.order_ids[0]
        confirmation_statuses = dict(getattr(confirmation, "statuses", {}))
        confirmation_open_order_states = dict(getattr(confirmation, "open_order_states", {}))
        submitted = True
        action = "submitted_protective_sell_stop"

    return ProtectionRepairRecord(
        timestamp=datetime.now(timezone.utc).isoformat(),
        symbol=symbol,
        position_qty=position_qty,
        avg_cost=avg_cost,
        market_price=market_price,
        uncovered_qty=uncovered,
        existing_stop_qty=existing_stop_qty,
        new_stop_qty=uncovered if not blocked else 0,
        raw_stop_price=raw_stop,
        normalized_stop_price=normalized,
        min_tick=float(DEFAULT_US_STOCK_MIN_TICK),
        stop_pct=(_float_or_none(preview.get("stop_pct")) or stop_config.default_pct) if preview is not None else stop_config.default_pct,
        stop_policy_reason=policy_reason,
        submitted_order_id=submitted_order_id,
        submitted=submitted,
        blocked_reason=blocked,
        action_taken=action,
        side=side,
        order_type=order_type,
        tif=tif,
        outside_rth=outside_rth,
        order_ref=order_ref,
        confirmation_statuses=confirmation_statuses,
        confirmation_open_order_states=confirmation_open_order_states,
        used_cached_state=False,
        force_refresh_required=force_refresh_required,
        force_refresh_performed=force_refresh_performed,
        force_refresh_ok=force_refresh_ok,
        state_stale=state_stale,
    )


def calculate_uncovered_qty(position_qty: float, protective_stop_qty: float) -> int:
    if position_qty <= 0:
        return 0
    uncovered = max(0.0, position_qty - max(0.0, protective_stop_qty))
    return int(uncovered)


def calculate_raw_stop_price(
    *,
    avg_cost: float | None,
    market_price: float | None,
    stop_pct: float,
) -> tuple[float | None, str]:
    if market_price is None or market_price <= 0:
        return None, "missing market price"
    pct = max(0.03, min(abs(stop_pct), 0.05))
    return market_price * (1 - pct), "current-price hard stop"


def load_stop_config() -> StopConfig:
    return StopConfig(
        mode=os.getenv("POSITION_STOP_MODE", "dynamic").strip().lower() or "dynamic",
        default_pct=_float_env("POSITION_STOP_DEFAULT_PCT", _float_env("POSITION_PROTECTION_DEFAULT_STOP_PCT", DEFAULT_STOP_PCT)),
        min_pct=_float_env("POSITION_STOP_MIN_PCT", MIN_STOP_PCT),
        max_pct=_float_env("POSITION_STOP_MAX_PCT", MAX_STOP_PCT),
        atr_multiplier=_float_env("POSITION_STOP_ATR_MULTIPLIER", ATR_MULTIPLIER),
        spread_multiplier=_float_env("POSITION_STOP_SPREAD_MULTIPLIER", SPREAD_MULTIPLIER),
        stale_ms=_float_env("POSITION_STOP_STALE_MS", STALE_QUOTE_MS),
        require_fresh_quote=_bool_env("POSITION_STOP_REQUIRE_FRESH_QUOTE", True),
        repair_max_per_cycle=int(_float_env("POSITION_PROTECTION_REPAIR_MAX_PER_CYCLE", REPAIR_MAX_PER_CYCLE)),
    )


def load_repair_config(*, enabled: bool | None = None) -> RepairConfig:
    mode = os.getenv("POSITION_PROTECTION_REPAIR_MODE", "test").strip().lower() or "test"
    if mode not in {"test", "run"}:
        mode = "test"
    return RepairConfig(
        enabled=_bool_env("POSITION_PROTECTION_REPAIR_ENABLED", False) if enabled is None else enabled,
        mode=mode,
        test_symbol=os.getenv("POSITION_PROTECTION_TEST_SYMBOL", "auto"),
        test_order_limit=int(_float_env("POSITION_PROTECTION_TEST_ORDER_LIMIT", 1)),
        run_max_orders=int(_float_env("POSITION_PROTECTION_RUN_MAX_ORDERS", 20)),
        run_require_test_success=_bool_env("POSITION_PROTECTION_RUN_REQUIRE_TEST_SUCCESS", True),
    )


def paper_operation_mode(repair_config: RepairConfig) -> str:
    if not repair_config.enabled:
        return "monitor_only"
    if repair_config.mode == "test":
        return "repair_test"
    return "paper_protection_run"


def build_repair_execution_plan(
    *,
    settings: Settings,
    preview: Mapping[str, Any],
    repair_config: RepairConfig,
) -> dict[str, Any]:
    base = {
        "allowed_repair_symbols": [],
        "run_allowed": False,
        "run_blocked_reason": "",
    }
    if not repair_config.enabled:
        base["run_blocked_reason"] = "POSITION_PROTECTION_REPAIR_ENABLED is false"
        return base
    if settings.trading_mode != "PAPER":
        base["run_blocked_reason"] = "live trading is not allowed"
        return base
    proposals = [item for item in preview.get("proposals", []) if _is_run_symbol_eligible(item)]
    if repair_config.mode == "test":
        selected = (preview.get("test_then_bulk") or {}).get("selected_test_symbol")
        if not selected:
            base["run_blocked_reason"] = (preview.get("test_then_bulk") or {}).get("selected_reason") or "no selected test symbol"
            return base
        base["allowed_repair_symbols"] = [selected]
        base["run_allowed"] = True
        return base
    if repair_config.mode != "run":
        base["run_blocked_reason"] = f"unsupported repair mode: {repair_config.mode}"
        return base
    if repair_config.run_require_test_success and not bool(latest_test_repair_result().get("success")):
        base["run_blocked_reason"] = "POSITION_PROTECTION_RUN_REQUIRE_TEST_SUCCESS is true but latest test repair success is not true"
        return base
    base["allowed_repair_symbols"] = [item["symbol"] for item in proposals[: max(0, repair_config.run_max_orders)]]
    base["run_allowed"] = bool(base["allowed_repair_symbols"])
    if not base["run_allowed"]:
        base["run_blocked_reason"] = "no eligible safe_to_repair symbols for run mode"
    return base


def latest_test_repair_result() -> dict[str, Any]:
    path = REPORT_DIR / "test_repair_result.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def build_test_repair_result(
    record: Mapping[str, Any],
    preview: Mapping[str, Any] | None,
    *,
    settings: Settings,
) -> dict[str, Any]:
    statuses = list((record.get("confirmation_statuses") or {}).values())
    states = list((record.get("confirmation_open_order_states") or {}).values())
    active = any(str(value) in ACTIVE_ORDER_STATUSES for value in statuses + states)
    coverage_before = float(record.get("existing_stop_qty") or 0.0)
    submitted_qty = int(float(record.get("new_stop_qty") or 0))
    coverage_after = coverage_before + submitted_qty if record.get("submitted") else coverage_before
    preview_stop = None if preview is None else _float_or_none(preview.get("proposed_stop_price"))
    outside_rth_requested = record.get("outside_rth") is True
    outside_rth_effective = record.get("outside_rth_effective")
    if outside_rth_effective is None:
        outside_rth_effective = record.get("outside_rth")
    outside_rth_supported = outside_rth_effective is True
    outside_rth_warning = (
        outside_rth_requested
        and outside_rth_effective is False
        and record.get("side") == "SELL"
        and record.get("order_type") == "STP"
    )
    outside_rth_warning_reason = (
        "IBKR/TWS plain STP appears RTH-only"
        if outside_rth_warning
        else ""
    )
    checks = {
        "active_protective_sell_stp": active,
        "side_sell": record.get("side") == "SELL",
        "order_type_stp": record.get("order_type") == "STP",
        "tif_gtc": record.get("tif") == "GTC",
        "outside_rth_requested": outside_rth_requested,
        "outside_rth_effective_or_explained": outside_rth_effective is True or outside_rth_warning,
        "order_ref_exists": bool(record.get("order_ref")),
        "qty_correct": preview is not None and submitted_qty == int(float(preview.get("uncovered_qty") or 0)),
        "stop_price_matches_preview": preview_stop is not None and _float_or_none(record.get("normalized_stop_price")) == preview_stop,
        "coverage_after_gt_before": coverage_after > coverage_before,
        "uncovered_qty_reduced": submitted_qty > 0,
        "no_buy_submitted": record.get("side") == "SELL",
        "live_not_enabled": settings.trading_mode == "PAPER",
    }
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "position_protection_test_repair_result",
        "symbol": record.get("symbol"),
        "order_id": record.get("submitted_order_id"),
        "order_ref": record.get("order_ref"),
        "side": record.get("side"),
        "order_type": record.get("order_type"),
        "tif": record.get("tif"),
        "outside_rth": record.get("outside_rth"),
        "outsideRth_requested": outside_rth_requested,
        "outsideRth_effective": outside_rth_effective,
        "outsideRth_supported": outside_rth_supported,
        "outsideRth_warning": outside_rth_warning,
        "outsideRth_warning_reason": outside_rth_warning_reason,
        "qty": submitted_qty,
        "stop_price": record.get("normalized_stop_price"),
        "preview_stop_price": preview_stop,
        "status_values": statuses,
        "open_order_state_values": states,
        "coverage_before": coverage_before,
        "coverage_after": coverage_after,
        "checks": checks,
        "success": all(checks.values()),
        "success_with_warning": all(checks.values()) and outside_rth_warning,
        "warning_reason": "outsideRth ineffective for plain STP" if outside_rth_warning else "",
        "blocks_run": not all(checks.values()),
    }


def write_test_repair_result(result: Mapping[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "test_repair_result.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    lines = [
        "# Position Protection Test Repair Result",
        "",
        f"- timestamp: {result.get('timestamp')}",
        f"- success: {result.get('success')}",
        f"- symbol: {result.get('symbol')}",
        f"- qty: {result.get('qty')}",
        f"- stop_price: {result.get('stop_price')}",
        f"- order_ref: {result.get('order_ref')}",
        f"- outsideRth_requested: {result.get('outsideRth_requested')}",
        f"- outsideRth_effective: {result.get('outsideRth_effective')}",
        f"- outsideRth_supported: {result.get('outsideRth_supported')}",
        f"- outsideRth_warning: {result.get('outsideRth_warning')}",
        f"- outsideRth_warning_reason: {result.get('outsideRth_warning_reason')}",
        f"- blocks_run: {result.get('blocks_run')}",
        "",
        "| Check | Passed |",
        "|---|---|",
    ]
    for key, value in (result.get("checks") or {}).items():
        lines.append(f"| {key} | {'yes' if value else 'no'} |")
    (REPORT_DIR / "test_repair_result.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def calculate_dynamic_stop(
    *,
    reference_price: float | None,
    bid: float | None,
    ask: float | None,
    atr: float | None,
    config: StopConfig,
) -> dict[str, float | None]:
    if reference_price is None or reference_price <= 0:
        return {
            "atr_pct": None,
            "spread_pct": None,
            "raw_stop_pct": None,
            "stop_pct": None,
            "raw_stop_price": None,
        }
    atr_pct = None if atr is None or atr <= 0 else atr / reference_price
    spread_pct = (ask - bid) / reference_price if bid is not None and ask is not None and ask >= bid else 0.0
    if config.mode != "dynamic":
        raw_stop_pct = config.default_pct
    elif atr_pct is not None:
        raw_stop_pct = max(
            config.min_pct,
            config.atr_multiplier * atr_pct,
            config.spread_multiplier * spread_pct,
        )
    else:
        raw_stop_pct = config.default_pct
    stop_pct = max(config.min_pct, min(raw_stop_pct, config.max_pct))
    return {
        "atr_pct": atr_pct,
        "spread_pct": spread_pct,
        "raw_stop_pct": raw_stop_pct,
        "stop_pct": stop_pct,
        "raw_stop_price": reference_price * (1 - stop_pct),
    }


def select_reference_price(*, bid: float | None, ask: float | None, last: float | None) -> float | None:
    if bid is not None and bid > 0:
        return bid
    if last is not None and last > 0:
        return last
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        return (bid + ask) / 2
    return None


def build_repair_preview_report(
    *,
    settings: Settings | None = None,
    guard_report: Mapping[str, Any] | None = None,
    stop_pct: float | None = None,
    stop_config: StopConfig | None = None,
    repair_config: RepairConfig | None = None,
) -> dict[str, Any]:
    settings = settings or Settings.load()
    config = stop_config or load_stop_config()
    repair = repair_config or load_repair_config()
    if stop_pct is not None:
        config = StopConfig(
            mode=config.mode,
            default_pct=stop_pct,
            min_pct=config.min_pct,
            max_pct=config.max_pct,
            atr_multiplier=config.atr_multiplier,
            spread_multiplier=config.spread_multiplier,
            stale_ms=config.stale_ms,
            require_fresh_quote=config.require_fresh_quote,
            repair_max_per_cycle=config.repair_max_per_cycle,
        )
    guard = dict(guard_report or build_position_guard_report(settings=settings))
    timestamp = datetime.now(timezone.utc).isoformat()
    proposals = [
        asdict(build_repair_preview_proposal(row, settings=settings, stop_config=config))
        for row in guard.get("symbols", [])
        if float(row.get("position_qty") or 0) > 0
    ]
    for item in proposals:
        item["preview_timestamp"] = timestamp
    test_then_bulk = asdict(
        select_test_then_bulk_symbol(
            proposals,
            test_symbol=repair.test_symbol,
            test_order_limit=repair.test_order_limit,
        )
    )
    test_success = bool(latest_test_repair_result().get("success"))
    run_allowed = True
    run_blocked_reason = ""
    if repair.mode == "run" and repair.run_require_test_success and not test_success:
        run_allowed = False
        run_blocked_reason = "POSITION_PROTECTION_RUN_REQUIRE_TEST_SUCCESS is true but latest test repair success is not true"
    report = {
        "timestamp": timestamp,
        "source": "position_protection_repair_preview",
        "mode": settings.trading_mode,
        "position_protection_repair_enabled": repair.enabled,
        "position_protection_repair_mode": repair.mode,
        "paper_operation_mode": paper_operation_mode(repair),
        "buy_freeze": _bool_env("MODE9_BUY_FREEZE", True),
        "live_enabled": _bool_env("LIVE_TRADING_ENABLED", False),
        "stop_mode": config.mode,
        "stop_pct": config.default_pct,
        "default_stop_pct": config.default_pct,
        "min_stop_pct": config.min_pct,
        "max_stop_pct": config.max_pct,
        "atr_multiplier": config.atr_multiplier,
        "spread_multiplier": config.spread_multiplier,
        "stale_ms": config.stale_ms,
        "require_fresh_quote": config.require_fresh_quote,
        "repair_max_per_cycle": config.repair_max_per_cycle,
        "repair_enabled": repair.enabled,
        "repair_mode": repair.mode,
        "test_order_limit": repair.test_order_limit,
        "run_max_orders": repair.run_max_orders,
        "run_require_test_success": repair.run_require_test_success,
        "test_repair_success": test_success,
        "run_allowed": run_allowed,
        "run_blocked_reason": run_blocked_reason,
        "mode9_buy_freeze": _bool_env("MODE9_BUY_FREEZE", True),
        "strategy_debt_ids": STOP_STRATEGY_DEBT_IDS,
        "test_then_bulk": test_then_bulk,
        "eligible_test_symbols": test_then_bulk["eligible_test_symbols"],
        "selected_test_symbol": test_then_bulk["selected_test_symbol"],
        "selected_reason": test_then_bulk["selected_reason"],
        "proposals": proposals,
        "safe_to_repair_symbols": [item["symbol"] for item in proposals if item["safe_to_repair"]],
        "manual_review_symbols": [item["symbol"] for item in proposals if item["manual_review_required"] or not item["safe_to_repair"]],
    }
    write_preview_report(report)
    return report


def select_test_then_bulk_symbol(
    proposals: Sequence[Mapping[str, Any]],
    *,
    test_symbol: str,
    test_order_limit: int,
) -> TestThenBulkSelection:
    mode = (test_symbol or "auto").strip().upper()
    eligible = [_test_symbol_row(item) for item in proposals if _is_test_symbol_eligible(item)]
    eligible = sorted(
        eligible,
        key=lambda item: (
            item["uncovered_notional"],
            item["uncovered_qty"],
            item["existing_stop_complexity"],
            item["symbol"],
        ),
    )
    if test_order_limit <= 0:
        return TestThenBulkSelection(
            test_symbol_mode=mode,
            test_order_limit=test_order_limit,
            eligible_test_symbols=eligible,
            selected_test_symbol=None,
            selected_reason="POSITION_PROTECTION_TEST_ORDER_LIMIT must be > 0",
            uncovered_qty=None,
            uncovered_notional=None,
            existing_stop_qty=None,
            proposed_stop_price=None,
        )
    if mode == "AUTO":
        if not eligible:
            return TestThenBulkSelection(
                test_symbol_mode="AUTO",
                test_order_limit=test_order_limit,
                eligible_test_symbols=[],
                selected_test_symbol=None,
                selected_reason="no eligible safe_to_repair symbol without manual review",
                uncovered_qty=None,
                uncovered_notional=None,
                existing_stop_qty=None,
                proposed_stop_price=None,
            )
        selected = eligible[0]
        return TestThenBulkSelection(
            test_symbol_mode="AUTO",
            test_order_limit=test_order_limit,
            eligible_test_symbols=eligible,
            selected_test_symbol=selected["symbol"],
            selected_reason="auto selected by lowest uncovered_notional, then uncovered_qty, existing_stop_complexity, symbol",
            uncovered_qty=selected["uncovered_qty"],
            uncovered_notional=selected["uncovered_notional"],
            existing_stop_qty=selected["existing_stop_qty"],
            proposed_stop_price=selected["proposed_stop_price"],
        )

    by_symbol = {str(item.get("symbol", "")).upper(): item for item in proposals}
    candidate = by_symbol.get(mode)
    rejection = _manual_test_symbol_rejection(candidate, mode)
    if rejection:
        return TestThenBulkSelection(
            test_symbol_mode=mode,
            test_order_limit=test_order_limit,
            eligible_test_symbols=eligible,
            selected_test_symbol=None,
            selected_reason=rejection,
            uncovered_qty=None,
            uncovered_notional=None,
            existing_stop_qty=None,
            proposed_stop_price=None,
        )
    selected = _test_symbol_row(candidate)
    return TestThenBulkSelection(
        test_symbol_mode=mode,
        test_order_limit=test_order_limit,
        eligible_test_symbols=eligible,
        selected_test_symbol=selected["symbol"],
        selected_reason=f"manual POSITION_PROTECTION_TEST_SYMBOL={mode} passed safety checks; first stage submits one repair order for full uncovered_qty",
        uncovered_qty=selected["uncovered_qty"],
        uncovered_notional=selected["uncovered_notional"],
        existing_stop_qty=selected["existing_stop_qty"],
        proposed_stop_price=selected["proposed_stop_price"],
    )


def build_repair_preview_proposal(
    row: Mapping[str, Any],
    *,
    settings: Settings,
    stop_pct: float | None = None,
    stop_config: StopConfig | None = None,
) -> RepairPreviewProposal:
    config = stop_config or load_stop_config()
    if stop_pct is not None:
        config = StopConfig(
            mode=config.mode,
            default_pct=stop_pct,
            min_pct=config.min_pct,
            max_pct=config.max_pct,
            atr_multiplier=config.atr_multiplier,
            spread_multiplier=config.spread_multiplier,
            stale_ms=config.stale_ms,
            require_fresh_quote=config.require_fresh_quote,
            repair_max_per_cycle=config.repair_max_per_cycle,
        )
    symbol = str(row.get("symbol", "")).upper()
    position_qty = float(row.get("position_qty") or 0.0)
    existing_stop_qty = float(row.get("protective_stop_qty") or 0.0)
    uncovered = calculate_uncovered_qty(position_qty, existing_stop_qty)
    avg_cost = _float_or_none(row.get("avg_cost"))
    bid = _float_or_none(row.get("bid"))
    ask = _float_or_none(row.get("ask"))
    last = _float_or_none(row.get("last")) or _float_or_none(row.get("market_price"))
    market_price = last
    current = select_reference_price(bid=bid, ask=ask, last=last)
    atr = _first_float(row, ("atr", "atr_14", "average_true_range"))
    stop_calc = calculate_dynamic_stop(reference_price=current, bid=bid, ask=ask, atr=atr, config=config)
    raw_stop = _float_or_none(stop_calc.get("raw_stop_price"))
    policy_reason = "dynamic ATR/spread stop" if stop_calc.get("atr_pct") is not None else "fallback default stop percent"
    normalized = None if raw_stop is None else normalize_order_price(
        symbol=symbol,
        side="SELL",
        order_type="STP",
        price=raw_stop,
    )
    existing_details = list(row.get("protective_stop_order_details", []))
    existing_stp_qty = _existing_order_qty(existing_details, exact_type="STP")
    existing_stp_lmt_qty = _existing_order_qty(existing_details, exact_type="STP LMT")
    outside_requested_existing = any(bool(item.get("outside_rth")) for item in existing_details)
    outside_effective_existing = bool(existing_details) and all(bool(item.get("outside_rth")) for item in existing_details)
    plain_stp_outside_warning = existing_stp_qty > 0 and not outside_effective_existing
    duplicate = _has_exact_duplicate_stop(existing_details, uncovered, normalized)
    overprotected = existing_stop_qty > position_qty
    quote_age = _quote_age_ms(row)
    quote_stale = bool(row.get("stale_quote_warning")) or (config.require_fresh_quote and (quote_age is None or quote_age > config.stale_ms))
    would_trigger = _would_trigger_immediately(normalized, bid=bid, last=last)
    stop_distance = None if normalized is None or current in {None, 0} else round((current - normalized) / current, 6)
    cost_distance = None if normalized is None or avg_cost in {None, 0} else round((avg_cost - normalized) / avg_cost, 6)
    estimated_loss = None
    estimated_pnl = None
    if normalized is not None and avg_cost is not None and uncovered > 0:
        estimated_loss = round(max(0.0, avg_cost - normalized) * uncovered, 4)
        estimated_pnl = round((normalized - avg_cost) * uncovered, 4)
    unrealized_pnl_pct = None if avg_cost in {None, 0} or current is None else round((current - avg_cost) / avg_cost, 6)
    manual_review_required = bool(unrealized_pnl_pct is not None and unrealized_pnl_pct <= -0.10)
    raw_limit = None if normalized is None else normalized * (1 - STOP_LIMIT_OFFSET_PCT)
    normalized_limit = None if raw_limit is None else normalize_order_price(
        symbol=symbol,
        side="SELL",
        order_type="LMT",
        price=raw_limit,
    )
    safe, reason = _preview_safety(
        settings=settings,
        proposed_qty=uncovered,
        position_qty=position_qty,
        existing_stop_qty=existing_stop_qty,
        normalized_stop_price=normalized,
        bid=bid,
        last=last,
        quote_stale=quote_stale,
        duplicate_risk=duplicate,
        overprotected_risk=overprotected,
        would_trigger_immediately=would_trigger,
        spread_warning=bool(row.get("spread_warning")),
        manual_review_required=manual_review_required,
    )
    blocked_reason = "" if safe else reason
    recommended_action = "create_protective_sell_stop_limit" if safe else "none"
    open_orders_count = int(row.get("open_buy_orders") or 0) + int(row.get("open_sell_orders") or 0)
    underprotected_qty = uncovered if 0 <= existing_stop_qty < position_qty else 0
    overprotected_qty = max(0.0, existing_stop_qty - position_qty)
    return RepairPreviewProposal(
        symbol=symbol,
        position_qty=position_qty,
        avg_cost=avg_cost,
        stop_mode=config.mode,
        average_cost=avg_cost,
        market_price=market_price,
        current_price=current,
        reference_price=current,
        bid=bid,
        ask=ask,
        last=last,
        quote_age_sec=None if quote_age is None else round(quote_age / 1000.0, 6),
        quote_age_ms=quote_age,
        open_orders_count_for_symbol=open_orders_count,
        existing_protective_qty=existing_stop_qty,
        existing_STP_qty=existing_stp_qty,
        existing_STP_LMT_qty=existing_stp_lmt_qty,
        outsideRth_requested_existing=outside_requested_existing,
        outsideRth_effective_existing=outside_effective_existing,
        plain_STP_outsideRth_warning=plain_stp_outside_warning,
        atr=atr,
        atr_pct=_round_pct(stop_calc.get("atr_pct")),
        spread_pct=_round_pct(stop_calc.get("spread_pct")),
        raw_stop_pct=_round_pct(stop_calc.get("raw_stop_pct")),
        stop_pct=_round_pct(stop_calc.get("stop_pct")),
        min_stop_pct=config.min_pct,
        max_stop_pct=config.max_pct,
        default_stop_pct=config.default_pct,
        existing_stop_qty=existing_stop_qty,
        uncovered_qty=uncovered,
        underprotected_qty=underprotected_qty,
        overprotected_qty=overprotected_qty,
        duplicate_protection_detected=duplicate,
        recommended_action=recommended_action,
        recommended_order_type="SELL STP LMT" if uncovered > 0 and not duplicate and not overprotected else "none",
        recommended_qty=uncovered if safe else 0,
        raw_limit_price=raw_limit,
        normalized_limit_price=normalized_limit,
        outsideRth_requested=True if uncovered > 0 else False,
        expected_outsideRth_supported=True if uncovered > 0 else False,
        execution_preview_allowed=safe,
        blocked_reason=blocked_reason,
        proposed_action=recommended_action,
        proposed_order_type="SELL STP LMT" if uncovered > 0 and not duplicate and not overprotected else "none",
        proposed_qty=uncovered if safe else 0,
        proposed_stop_price=normalized,
        raw_stop_price=raw_stop,
        stop_distance_pct=None if stop_distance is None else round(stop_distance * 100, 4),
        cost_stop_distance_pct=None if cost_distance is None else round(cost_distance * 100, 4),
        estimated_loss_if_triggered=estimated_loss,
        estimated_pnl_if_stop_triggered=estimated_pnl,
        unrealized_pnl_pct=None if unrealized_pnl_pct is None else round(unrealized_pnl_pct * 100, 4),
        would_trigger_immediately=would_trigger,
        duplicate_risk=duplicate,
        overprotected_risk=overprotected,
        quote_stale=quote_stale,
        manual_review_required=manual_review_required,
        safe_to_repair=safe,
        reason=reason if reason else policy_reason,
        strategy_debt_ids=STOP_STRATEGY_DEBT_IDS,
        existing_stop_details=[dict(item) for item in existing_details],
    )


def write_preview_report(report: Mapping[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "repair_preview.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    (REPORT_DIR / "repair_preview.md").write_text(_preview_markdown(report), encoding="utf-8")


def write_report(report: Mapping[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "latest.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    with (REPORT_DIR / "history.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, sort_keys=True) + "\n")


def _blocked_reason(
    row: Mapping[str, Any],
    *,
    settings: Settings,
    enabled: bool,
    uncovered_qty: int,
    raw_stop_price: float | None,
    normalized_stop_price: float | None,
    preview: Mapping[str, Any] | None = None,
) -> str:
    if not enabled:
        return "POSITION_PROTECTION_REPAIR_ENABLED is false"
    if preview is None or preview.get("safe_to_repair") is not True:
        return "repair preview is not safe_to_repair"
    if _preview_age_seconds(preview) > 120:
        return "repair preview is expired"
    if settings.trading_mode != "PAPER":
        return "live trading is not allowed for position protection"
    lock = read_lock()
    if not lock or lock.get("process_name") != "mode9_autonomous_agent":
        return "execution-writer lock is not held by Mode 9"
    if uncovered_qty <= 0:
        return "no uncovered long quantity"
    if row.get("stale_quote_warning"):
        return "quote is stale"
    if row.get("spread_warning"):
        return "spread is too wide"
    if raw_stop_price is None or normalized_stop_price is None or normalized_stop_price <= 0:
        return "invalid stop price"
    market_price = _float_or_none(row.get("market_price"))
    if market_price is not None and normalized_stop_price >= market_price:
        return "normalized stop price is not below current market price"
    return ""


def _preview_safety(
    *,
    settings: Settings,
    proposed_qty: int,
    position_qty: float,
    existing_stop_qty: float,
    normalized_stop_price: float | None,
    bid: float | None,
    last: float | None,
    quote_stale: bool,
    duplicate_risk: bool,
    overprotected_risk: bool,
    would_trigger_immediately: bool,
    spread_warning: bool,
    manual_review_required: bool,
) -> tuple[bool, str]:
    if settings.trading_mode != "PAPER":
        return False, "live trading is not allowed"
    if proposed_qty <= 0:
        return False, "no uncovered quantity to protect"
    if existing_stop_qty + proposed_qty > position_qty:
        return False, "proposed stop quantity would exceed current position"
    if normalized_stop_price is None or normalized_stop_price <= 0:
        return False, "invalid proposed stop price"
    reference = bid or last
    if reference is None:
        return False, "missing bid/last quote"
    if normalized_stop_price >= reference:
        return False, "proposed stop price is not below current bid/last"
    if quote_stale:
        return False, "quote is stale"
    if spread_warning:
        return False, "spread is too wide"
    if manual_review_required:
        return False, "manual review required because unrealized loss exceeds 10%"
    if duplicate_risk:
        return False, "exact duplicate stop risk"
    if overprotected_risk:
        return False, "existing stops exceed current position"
    if would_trigger_immediately:
        return False, "proposed stop may trigger immediately"
    return True, "safe_to_repair dry-run checks passed"


def _is_test_symbol_eligible(item: Mapping[str, Any]) -> bool:
    return (
        item.get("safe_to_repair") is True
        and item.get("manual_review_required") is False
        and int(float(item.get("uncovered_qty") or 0)) > 0
    )


def _is_run_symbol_eligible(item: Mapping[str, Any]) -> bool:
    return _is_test_symbol_eligible(item)


def _test_symbol_row(item: Mapping[str, Any]) -> dict[str, Any]:
    reference = _float_or_none(item.get("reference_price")) or _float_or_none(item.get("current_price")) or 0.0
    uncovered_qty = int(float(item.get("uncovered_qty") or 0))
    existing_details = item.get("existing_stop_details") or []
    existing_stop_complexity = len(existing_details) if isinstance(existing_details, list) else 0
    return {
        "symbol": str(item.get("symbol", "")).upper(),
        "uncovered_qty": uncovered_qty,
        "uncovered_notional": round(uncovered_qty * reference, 4),
        "reference_price": reference,
        "existing_stop_qty": float(item.get("existing_stop_qty") or 0.0),
        "existing_stop_complexity": existing_stop_complexity,
        "proposed_stop_price": _float_or_none(item.get("proposed_stop_price")),
        "safe_to_repair": item.get("safe_to_repair") is True,
        "manual_review_required": item.get("manual_review_required") is True,
    }


def _manual_test_symbol_rejection(candidate: Mapping[str, Any] | None, symbol: str) -> str:
    if candidate is None:
        return f"manual POSITION_PROTECTION_TEST_SYMBOL={symbol} does not exist in repair_preview"
    if int(float(candidate.get("uncovered_qty") or 0)) <= 0:
        return f"manual POSITION_PROTECTION_TEST_SYMBOL={symbol} rejected because uncovered_qty<=0"
    if candidate.get("safe_to_repair") is not True:
        return f"manual POSITION_PROTECTION_TEST_SYMBOL={symbol} rejected because safe_to_repair=false: {candidate.get('reason')}"
    if candidate.get("manual_review_required") is True:
        return f"manual POSITION_PROTECTION_TEST_SYMBOL={symbol} rejected because manual_review_required=true"
    return ""


def _preview_age_seconds(preview: Mapping[str, Any]) -> float:
    timestamp = preview.get("timestamp")
    if not timestamp:
        return 0.0
    try:
        parsed = datetime.fromisoformat(str(timestamp))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()


def _has_exact_duplicate_stop(
    existing_details: Sequence[Mapping[str, Any]],
    proposed_qty: int,
    proposed_stop_price: float | None,
) -> bool:
    if proposed_stop_price is None or proposed_qty <= 0:
        return False
    for item in existing_details:
        if str(item.get("action", "")).upper() != "SELL":
            continue
        if not str(item.get("order_type", "")).upper().startswith("STP"):
            continue
        if int(float(item.get("total_quantity") or 0)) == proposed_qty and _float_or_none(item.get("aux_price")) == proposed_stop_price:
            return True
    return False


def _existing_order_qty(existing_details: Sequence[Mapping[str, Any]], *, exact_type: str) -> float:
    expected = exact_type.upper()
    total = 0.0
    for item in existing_details:
        if str(item.get("action", "")).upper() != "SELL":
            continue
        if str(item.get("order_type", "")).upper() != expected:
            continue
        total += float(item.get("total_quantity") or 0.0)
    return total


def _would_trigger_immediately(stop_price: float | None, *, bid: float | None, last: float | None) -> bool:
    if stop_price is None:
        return False
    reference = bid or last
    return reference is not None and stop_price >= reference


def _preview_markdown(report: Mapping[str, Any]) -> str:
    proposals = list(report.get("proposals", []))
    fully = [item["symbol"] for item in proposals if item.get("uncovered_qty") == 0 and not item.get("overprotected_risk")]
    under = [item["symbol"] for item in proposals if float(item.get("existing_protective_qty") or 0) > 0 and int(float(item.get("underprotected_qty") or 0)) > 0]
    unprotected = [item["symbol"] for item in proposals if float(item.get("existing_protective_qty") or 0) == 0 and int(float(item.get("uncovered_qty") or 0)) > 0]
    over = [item["symbol"] for item in proposals if float(item.get("overprotected_qty") or 0) > 0 or item.get("overprotected_risk")]
    duplicate = [item["symbol"] for item in proposals if item.get("duplicate_protection_detected") or item.get("duplicate_risk")]
    plain_stp_warning = [item["symbol"] for item in proposals if item.get("plain_STP_outsideRth_warning")]
    eligible = [item for item in proposals if item.get("execution_preview_allowed")]
    blocked = [item for item in proposals if not item.get("execution_preview_allowed")]
    eligible_symbols = ", ".join(str(item.get("symbol")) for item in eligible) if eligible else "none"
    blocked_reasons = "; ".join(
        f"{item.get('symbol')}: {item.get('blocked_reason') or item.get('reason')}"
        for item in blocked
    ) if blocked else "none"
    proposed_quantities = ", ".join(
        f"{item.get('symbol')}={item.get('recommended_qty')}"
        for item in eligible
    ) if eligible else "none"
    lines = [
        "# Position Protection Repair Preview",
        "",
        f"- 生成时间: {report.get('timestamp')}",
        f"- 模式: {report.get('mode')}",
        f"- stop_mode: {report.get('stop_mode')}",
        f"- default_stop_pct: {float(report.get('default_stop_pct') or report.get('stop_pct') or 0) * 100:.2f}%",
        f"- min_stop_pct: {float(report.get('min_stop_pct') or 0) * 100:.2f}%",
        f"- max_stop_pct: {float(report.get('max_stop_pct') or 0) * 100:.2f}%",
        f"- repair_enabled: {report.get('repair_enabled')}",
        f"- MODE9_BUY_FREEZE: {report.get('mode9_buy_freeze')}",
        f"- STRATEGY_DEBT: {', '.join(report.get('strategy_debt_ids', []))}",
        f"- test_symbol_mode: {(report.get('test_then_bulk') or {}).get('test_symbol_mode')}",
        f"- test_order_limit: {(report.get('test_then_bulk') or {}).get('test_order_limit')} repair order(s)",
        f"- selected_test_symbol: {(report.get('test_then_bulk') or {}).get('selected_test_symbol')}",
        f"- selected_reason: {(report.get('test_then_bulk') or {}).get('selected_reason')}",
        f"- total_proposed_paper_protective_SELL_STP_LMT_orders: {len(eligible)}",
        f"- orders_submitted: 0",
        f"- orders_cancelled: 0",
        "",
        "## Summary",
        "",
        f"- Symbols fully protected: {', '.join(fully) if fully else 'none'}",
        f"- Symbols underprotected: {', '.join(under) if under else 'none'}",
        f"- Symbols unprotected: {', '.join(unprotected) if unprotected else 'none'}",
        f"- Symbols overprotected: {', '.join(over) if over else 'none'}",
        f"- Symbols with duplicate protection: {', '.join(duplicate) if duplicate else 'none'}",
        f"- Symbols with only plain STP / outside-RTH warning: {', '.join(plain_stp_warning) if plain_stp_warning else 'none'}",
        f"- Symbols eligible for paper STP LMT repair: {eligible_symbols}",
        f"- Symbols blocked and why: {blocked_reasons}",
        f"- Total proposed quantity per symbol: {proposed_quantities}",
        "- Confirmation: no orders were submitted or cancelled.",
        "",
        "| Symbol | Position | Avg Cost | Bid | Ask | Last | Quote Age Sec | Open Orders | Existing Protective | STP | STP LMT | Uncovered | Under | Over | Dup | Plain STP RTH Warning | Recommended | Qty | Stop | Limit | Allowed | Blocked Reason |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---:|---:|---:|---|---|",
    ]
    for item in proposals:
        lines.append(
            "| {symbol} | {position_qty} | {avg_cost} | {bid} | {ask} | {last} | {quote_age} | {open_orders} | {existing} | {stp} | {stp_lmt} | {uncovered} | {under} | {over} | {dup} | {plain_warning} | {order_type} | {qty} | {stop} | {limit} | {allowed} | {blocked} |".format(
                symbol=item.get("symbol"),
                position_qty=item.get("position_qty"),
                avg_cost=_fmt(item.get("avg_cost")),
                bid=_fmt(item.get("bid")),
                ask=_fmt(item.get("ask")),
                last=_fmt(item.get("last")),
                quote_age=_fmt(item.get("quote_age_sec")),
                open_orders=item.get("open_orders_count_for_symbol"),
                existing=_fmt(item.get("existing_protective_qty")),
                stp=_fmt(item.get("existing_STP_qty")),
                stp_lmt=_fmt(item.get("existing_STP_LMT_qty")),
                uncovered=item.get("uncovered_qty"),
                under=item.get("underprotected_qty"),
                over=_fmt(item.get("overprotected_qty")),
                dup="yes" if item.get("duplicate_protection_detected") else "no",
                plain_warning="yes" if item.get("plain_STP_outsideRth_warning") else "no",
                order_type=item.get("recommended_order_type"),
                qty=item.get("recommended_qty"),
                stop=_fmt(item.get("proposed_stop_price")),
                limit=_fmt(item.get("normalized_limit_price")),
                allowed="yes" if item.get("execution_preview_allowed") else "no",
                blocked=str(item.get("blocked_reason") or item.get("reason", "")).replace("|", "/"),
            )
        )
    lines.extend(
        [
            "",
            "## Test Then Bulk",
            "",
            "| Symbol | Uncovered Qty | Uncovered Notional | Existing Stop Qty | Stop | Complexity |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for item in (report.get("test_then_bulk") or {}).get("eligible_test_symbols", []):
        lines.append(
            "| {symbol} | {qty} | {notional} | {existing} | {stop} | {complexity} |".format(
                symbol=item.get("symbol"),
                qty=item.get("uncovered_qty"),
                notional=_fmt(item.get("uncovered_notional")),
                existing=_fmt(item.get("existing_stop_qty")),
                stop=_fmt(item.get("proposed_stop_price")),
                complexity=item.get("existing_stop_complexity"),
            )
        )
    lines.extend(
        [
            "",
            "## 中文总结",
            "",
            "dry-run 表示只读取账户、行情和订单状态，生成建议保护单预览，不提交订单。",
            "动态 stop 会优先使用 ATR% 和 spread%，ATR 缺失时回落到 default_stop_pct。",
            "test_then_bulk 的 order limit 限制第一阶段 repair 订单数量，不限制股票股数；选中 symbol 会按 uncovered_qty 一次补齐。",
            "只有 execution_preview_allowed=true 且 POSITION_PROTECTION_REPAIR_ENABLED=true 时，后续 repair 流程才允许提交 paper 保护单；本次只生成 SELL STP LMT 预览。",
            "本报告不会取消已有 stop，也不会提交 BUY。",
        ]
    )
    return "\n".join(lines) + "\n"


def _fmt(value: object) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return str(value)


def _pct_fmt(value: object) -> str:
    number = _float_or_none(value)
    return "" if number is None else f"{number * 100:.4f}%"


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _float_or_none(value: object) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _quote_age_ms(row: Mapping[str, Any]) -> float | None:
    age_ms = _float_or_none(row.get("quote_age_ms"))
    if age_ms is not None:
        return age_ms
    age_sec = _float_or_none(row.get("quote_age_sec"))
    if age_sec is not None:
        return age_sec * 1000.0
    ages = [
        _float_or_none(row.get("bid_age_sec")),
        _float_or_none(row.get("ask_age_sec")),
        _float_or_none(row.get("last_age_sec")),
    ]
    ages = [age for age in ages if age is not None]
    return None if not ages else min(ages) * 1000.0


def _first_float(row: Mapping[str, Any], keys: Sequence[str]) -> float | None:
    for key in keys:
        value = _float_or_none(row.get(key))
        if value is not None:
            return value
    return None


def _round_pct(value: object) -> float | None:
    number = _float_or_none(value)
    return None if number is None else round(number, 6)


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return float(default)
    try:
        return float(value)
    except ValueError:
        return float(default)
