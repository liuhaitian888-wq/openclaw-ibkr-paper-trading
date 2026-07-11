import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from trading.config import PROJECT_ROOT, Settings
from trading.price_normalizer import normalize_order_price
from trading.process_guard import read_lock


REPORT_DIR = PROJECT_ROOT / "reports" / "gap_escape"


@dataclass(frozen=True)
class GapEscapeConfig:
    enabled: bool = True
    paper_only: bool = True
    trigger_pct: float = 0.08
    account_loss_trigger_pct: float = 0.01
    unfilled_seconds: float = 30.0
    max_slippage_pct: float = 0.01
    use_marketable_limit: bool = True
    max_position_fraction_per_step: float = 0.50
    min_seconds_between_steps: float = 60.0
    require_fresh_quote: bool = True
    max_spread_pct: float = 0.02


def load_gap_escape_config() -> GapEscapeConfig:
    return GapEscapeConfig(
        enabled=_bool_env("GAP_ESCAPE_ENABLED", True),
        paper_only=_bool_env("GAP_ESCAPE_PAPER_ONLY", True),
        trigger_pct=_float_env("GAP_ESCAPE_TRIGGER_PCT", 0.08),
        account_loss_trigger_pct=_float_env("GAP_ESCAPE_ACCOUNT_LOSS_TRIGGER_PCT", 0.01),
        unfilled_seconds=_float_env("GAP_ESCAPE_UNFILLED_SECONDS", 30.0),
        max_slippage_pct=_float_env("GAP_ESCAPE_MAX_SLIPPAGE_PCT", 0.01),
        use_marketable_limit=_bool_env("GAP_ESCAPE_USE_MARKETABLE_LIMIT", True),
        max_position_fraction_per_step=_float_env("GAP_ESCAPE_MAX_POSITION_FRACTION_PER_STEP", 0.50),
        min_seconds_between_steps=_float_env("GAP_ESCAPE_MIN_SECONDS_BETWEEN_STEPS", 60.0),
        require_fresh_quote=_bool_env("GAP_ESCAPE_REQUIRE_FRESH_QUOTE", True),
        max_spread_pct=_float_env("GAP_ESCAPE_MAX_SPREAD_PCT", 0.02),
    )


def build_gap_escape_report(
    *,
    position_guard: Mapping[str, Any],
    gap_risk_report: Mapping[str, Any] | None = None,
    event_risk_report: Mapping[str, Any] | None = None,
    settings: Settings | None = None,
    config: GapEscapeConfig | None = None,
) -> dict[str, Any]:
    settings = settings or Settings.load()
    config = config or load_gap_escape_config()
    loss_by_symbol = _worst_loss_by_symbol(gap_risk_report or {})
    event_by_symbol = {str(row.get("symbol", "")).upper(): row for row in (event_risk_report or {}).get("symbols", []) if isinstance(row, Mapping)}
    rows = [
        gap_escape_row(row, settings=settings, config=config, worst_loss=loss_by_symbol.get(str(row.get("symbol", "")).upper()), event=event_by_symbol.get(str(row.get("symbol", "")).upper(), {}))
        for row in position_guard.get("symbols", [])
        if isinstance(row, Mapping) and float(row.get("position_qty") or 0) > 0
    ]
    report = {
        "timestamp": _now(),
        "source": "gap_escape_manager",
        "config": asdict(config),
        "paper_only": settings.trading_mode == "PAPER",
        "live_enabled": settings.trading_mode not in {"PAPER", "DRY_RUN"},
        "symbols": rows,
        "submitted_count": 0,
        "status": "warning" if any(row["emergency_action_allowed"] for row in rows) else "ok",
    }
    write_report(report)
    return report


def gap_escape_row(
    position: Mapping[str, Any],
    *,
    settings: Settings,
    config: GapEscapeConfig,
    worst_loss: Mapping[str, Any] | None = None,
    event: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    symbol = str(position.get("symbol", "")).upper()
    qty = float(position.get("position_qty") or 0)
    bid = _float(position.get("bid"))
    ask = _float(position.get("ask"))
    last = _float(position.get("last") or position.get("market_price"))
    avg_cost = _float(position.get("avg_cost"))
    spread_pct = ((ask - bid) / last) if bid is not None and ask is not None and last and last > 0 and ask >= bid else None
    active_stop = _active_stop_price(position)
    active_stop_limit = _active_stop_limit_price(position)
    gap_pct = ((bid - avg_cost) / avg_cost) if bid is not None and avg_cost and avg_cost > 0 else 0.0
    estimated_loss_pct = _float((worst_loss or {}).get("estimated_account_loss_pct")) or 0.0
    trigger_reason = _trigger_reason(
        bid=bid,
        active_stop=active_stop,
        active_stop_limit=active_stop_limit,
        gap_pct=gap_pct,
        estimated_loss_pct=estimated_loss_pct,
        event=event or {},
        config=config,
    )
    blocked = gap_escape_blocked_reason(position, settings=settings, config=config, spread_pct=spread_pct)
    allowed = bool(trigger_reason and not blocked)
    raw_limit = bid * (1 - config.max_slippage_pct) if bid is not None else None
    normalized = None if raw_limit is None else normalize_order_price(symbol=symbol, side="SELL", order_type="LMT", price=raw_limit, log=False)
    sell_qty = min(int(qty), max(1, int(qty * config.max_position_fraction_per_step))) if qty > 0 else 0
    return {
        "timestamp": _now(),
        "symbol": symbol,
        "position_qty": qty,
        "bid": bid,
        "ask": ask,
        "last": last,
        "spread_pct": None if spread_pct is None else round(spread_pct, 6),
        "active_stop_price": active_stop,
        "active_stop_limit_price": active_stop_limit,
        "gap_pct": round(gap_pct, 6),
        "estimated_account_loss_pct": estimated_loss_pct,
        "trigger_reason": trigger_reason,
        "emergency_action_allowed": allowed,
        "order_type": "SELL LMT" if allowed else None,
        "sell_qty": sell_qty if allowed else 0,
        "raw_emergency_limit_price": raw_limit,
        "normalized_emergency_limit_price": normalized,
        "submitted": False,
        "blocked_reason": blocked,
        "action_taken": "paper_emergency_sell_lmt_plan_only" if allowed else "blocked_or_not_triggered",
        "decision_chain": [
            {"step": "trigger_bid_vs_stop", "condition": "bid <= active_stop_price", "value": bool(bid is not None and active_stop is not None and bid <= active_stop)},
            {"step": "trigger_bid_vs_stop_limit", "condition": "bid < active_stop_limit_price", "value": bool(bid is not None and active_stop_limit is not None and bid < active_stop_limit)},
            {"step": "trigger_gap_pct", "condition": "gap_pct <= -GAP_ESCAPE_TRIGGER_PCT", "gap_pct": round(gap_pct, 6), "threshold": -config.trigger_pct},
            {"step": "trigger_account_loss", "condition": "estimated_account_loss_pct >= GAP_ESCAPE_ACCOUNT_LOSS_TRIGGER_PCT", "value": estimated_loss_pct, "threshold": config.account_loss_trigger_pct},
            {"step": "paper_only", "value": settings.trading_mode == "PAPER"},
            {"step": "mode9_lock_required", "blocked_reason": blocked if "lock" in blocked.lower() else ""},
            {"step": "quote_fresh", "quote_age_ms": position.get("quote_age_ms"), "max_allowed_ms": 5000},
            {"step": "spread_check", "spread_pct": None if spread_pct is None else round(spread_pct, 6), "max_spread_pct": config.max_spread_pct},
            {"step": "sell_qty_cap", "formula": "min(position_qty, floor(position_qty * max_fraction))", "value": sell_qty if allowed else 0},
            {"step": "marketable_limit", "formula": "bid * (1 - max_slippage_pct)", "raw": raw_limit, "normalized": normalized},
            {"step": "submitted", "value": False, "reason": "report/planning only in this implementation"},
        ],
    }


def gap_escape_blocked_reason(position: Mapping[str, Any], *, settings: Settings, config: GapEscapeConfig, spread_pct: float | None) -> str:
    if not config.enabled:
        return "GAP_ESCAPE_ENABLED is false"
    if config.paper_only and settings.trading_mode != "PAPER":
        return "paper only required"
    if settings.trading_mode not in {"PAPER", "DRY_RUN"}:
        return "live trading is not allowed"
    lock = read_lock()
    if not lock or lock.get("process_name") != "mode9_autonomous_agent":
        return "Mode 9 execution-writer lock required"
    if config.require_fresh_quote and (position.get("quote_age_ms") is None or float(position.get("quote_age_ms") or 0) > 5_000):
        return "quote is stale"
    if spread_pct is None:
        return "missing spread"
    if spread_pct > config.max_spread_pct:
        return "spread is too wide"
    return ""


def _trigger_reason(*, bid: float | None, active_stop: float | None, active_stop_limit: float | None, gap_pct: float, estimated_loss_pct: float, event: Mapping[str, Any], config: GapEscapeConfig) -> str:
    if bid is not None and active_stop is not None and bid <= active_stop:
        return "bid <= active_stop_price"
    if bid is not None and active_stop_limit is not None and bid < active_stop_limit:
        return "bid < active_stop_limit_price"
    if gap_pct <= -config.trigger_pct:
        return "gap_pct below trigger"
    if estimated_loss_pct >= config.account_loss_trigger_pct:
        return "estimated_account_loss_pct above trigger"
    if float(event.get("event_risk_score") or 0) >= 0.7 and gap_pct <= -(config.trigger_pct / 2):
        return "high event risk with price gap"
    return ""


def _active_stop_price(position: Mapping[str, Any]) -> float | None:
    stops = position.get("protective_stop_order_details") or []
    prices = [_float(order.get("aux_price")) for order in stops if isinstance(order, Mapping)]
    prices = [price for price in prices if price is not None]
    return max(prices) if prices else None


def _active_stop_limit_price(position: Mapping[str, Any]) -> float | None:
    stops = position.get("protective_stop_order_details") or []
    prices = [_float(order.get("limit_price")) for order in stops if isinstance(order, Mapping) and _float(order.get("limit_price")) not in (None, 0.0)]
    return max(prices) if prices else None


def _worst_loss_by_symbol(report: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in report.get("symbols", []):
        if not isinstance(row, Mapping):
            continue
        symbol = str(row.get("symbol", "")).upper()
        if symbol not in result or float(row.get("estimated_account_loss_pct") or 0) > float(result[symbol].get("estimated_account_loss_pct") or 0):
            result[symbol] = row
    return result


def write_report(report: Mapping[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "latest.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    with (REPORT_DIR / "history.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, sort_keys=True) + "\n")


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float) -> float:
    return _float(os.getenv(name)) or default


def _float(value: object) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
