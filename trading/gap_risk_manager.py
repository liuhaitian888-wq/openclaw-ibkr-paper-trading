import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from trading.config import PROJECT_ROOT


REPORT_DIR = PROJECT_ROOT / "reports" / "gap_risk"


@dataclass(frozen=True)
class GapRiskConfig:
    max_symbol_loss_pct: float = 0.01
    max_portfolio_loss_pct: float = 0.03
    default_shock_pct: float = 0.30
    mega_cap_shock_pct: float = 0.15
    high_vol_shock_pct: float = 0.35
    new_listing_shock_pct: float = 0.50
    biotech_shock_pct: float = 0.60
    event_multiplier: float = 1.5


def load_gap_risk_config() -> GapRiskConfig:
    return GapRiskConfig(
        max_symbol_loss_pct=_float_env("GAP_RISK_MAX_SYMBOL_LOSS_PCT", 0.01),
        max_portfolio_loss_pct=_float_env("GAP_RISK_MAX_PORTFOLIO_LOSS_PCT", 0.03),
        default_shock_pct=_float_env("GAP_RISK_DEFAULT_SHOCK_PCT", 0.30),
        mega_cap_shock_pct=_float_env("GAP_RISK_MEGA_CAP_SHOCK_PCT", 0.15),
        high_vol_shock_pct=_float_env("GAP_RISK_HIGH_VOL_SHOCK_PCT", 0.35),
        new_listing_shock_pct=_float_env("GAP_RISK_NEW_LISTING_SHOCK_PCT", 0.50),
        biotech_shock_pct=_float_env("GAP_RISK_BIOTECH_SHOCK_PCT", 0.60),
        event_multiplier=_float_env("GAP_RISK_EVENT_MULTIPLIER", 1.5),
    )


def build_gap_risk_report(
    *,
    position_guard: Mapping[str, Any],
    account_net_liquidation: float | None = None,
    event_risk_report: Mapping[str, Any] | None = None,
    config: GapRiskConfig | None = None,
) -> dict[str, Any]:
    config = config or load_gap_risk_config()
    net_liq = account_net_liquidation or _latest_net_liquidation() or 0.0
    event_by_symbol = {
        str(item.get("symbol", "")).upper(): item
        for item in (event_risk_report or {}).get("symbols", [])
        if isinstance(item, Mapping)
    }
    rows = []
    risk_events = []
    for position in _long_positions(position_guard):
        symbol = str(position.get("symbol", "")).upper()
        market_price = _float(position.get("market_price") or position.get("last"))
        qty = _float(position.get("position_qty")) or 0.0
        avg_cost = _float(position.get("avg_cost"))
        notional = max(0.0, qty * (market_price or 0.0))
        base_shock = classify_symbol_shock(symbol, config)
        event = event_by_symbol.get(symbol, {})
        event_shock = _float(event.get("event_adjusted_gap_shock"))
        shocks = [-0.05, -0.10, -0.20, -0.30, -0.50, -(event_shock or base_shock)]
        for shock in _dedupe_shocks(shocks):
            row = gap_risk_row(
                symbol=symbol,
                position_qty=qty,
                market_price=market_price,
                avg_cost=avg_cost,
                account_net_liquidation=net_liq,
                shock_pct=abs(shock),
                max_symbol_loss_pct=config.max_symbol_loss_pct,
                position_notional=notional,
            )
            rows.append(row)
            if row["over_budget"]:
                risk_events.append(
                    {
                        "symbol": symbol,
                        "shock_pct": row["shock_pct"],
                        "estimated_gap_loss": row["estimated_gap_loss"],
                        "recommended_action": row["recommended_action"],
                    }
                )
    report = {
        "timestamp": _now(),
        "source": "gap_risk_manager",
        "config": asdict(config),
        "account_net_liquidation": net_liq,
        "symbols": rows,
        "risk_events": risk_events,
        "status": "warning" if risk_events else "ok",
    }
    write_report(report)
    return report


def gap_risk_row(
    *,
    symbol: str,
    position_qty: float,
    market_price: float | None,
    avg_cost: float | None,
    account_net_liquidation: float,
    shock_pct: float,
    max_symbol_loss_pct: float,
    position_notional: float | None = None,
) -> dict[str, Any]:
    notional = position_notional if position_notional is not None else position_qty * (market_price or 0.0)
    estimated_loss = notional * shock_pct
    max_loss = account_net_liquidation * max_symbol_loss_pct
    max_notional = max_loss / shock_pct if shock_pct > 0 else 0.0
    over = notional > max_notional if max_notional > 0 else False
    return {
        "symbol": symbol,
        "position_qty": position_qty,
        "market_price": market_price,
        "position_notional": round(notional, 4),
        "avg_cost": avg_cost,
        "account_net_liquidation": account_net_liquidation,
        "shock_pct": round(shock_pct, 6),
        "estimated_gap_loss": round(estimated_loss, 4),
        "estimated_account_loss_pct": round(estimated_loss / account_net_liquidation, 6) if account_net_liquidation > 0 else None,
        "max_allowed_symbol_gap_loss": round(max_loss, 4),
        "max_allowed_position_notional": round(max_notional, 4),
        "over_budget": over,
        "recommended_action": "reduce_position_or_hedge" if over else "hold_with_layered_protection",
        "decision_chain": [
            {"step": "position_notional", "formula": "position_qty * market_price", "value": round(notional, 4)},
            {"step": "estimated_gap_loss", "formula": "position_notional * shock_pct", "value": round(estimated_loss, 4)},
            {"step": "max_allowed_symbol_gap_loss", "formula": "account_net_liquidation * GAP_RISK_MAX_SYMBOL_LOSS_PCT", "value": round(max_loss, 4)},
            {"step": "max_allowed_position_notional", "formula": "max_allowed_symbol_gap_loss / shock_pct", "value": round(max_notional, 4)},
            {"step": "over_budget", "comparison": "position_notional > max_allowed_position_notional", "value": over},
        ],
    }


def classify_symbol_shock(symbol: str, config: GapRiskConfig) -> float:
    high_vol = {"NIO", "TSLA", "AMD", "MU", "INTC"}
    mega_cap = {"AAPL", "MSFT", "META", "GOOGL", "AMZN", "NVDA"}
    biotech_markers = ("BIIB", "MRNA", "BNTX", "REGN", "VRTX")
    if symbol in mega_cap:
        return config.mega_cap_shock_pct
    if symbol in high_vol:
        return config.high_vol_shock_pct
    if symbol in biotech_markers:
        return config.biotech_shock_pct
    return config.default_shock_pct


def write_report(report: Mapping[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "latest.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    with (REPORT_DIR / "history.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, sort_keys=True) + "\n")


def _long_positions(position_guard: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [
        row for row in position_guard.get("symbols", [])
        if isinstance(row, Mapping) and (_float(row.get("position_qty")) or 0.0) > 0
    ]


def _latest_net_liquidation() -> float | None:
    path = PROJECT_ROOT / "reports" / "account" / "latest.json"
    if not path.exists():
        return None
    try:
        return _float(json.loads(path.read_text(encoding="utf-8")).get("net_liquidation"))
    except json.JSONDecodeError:
        return None


def _dedupe_shocks(values: Sequence[float]) -> list[float]:
    seen = set()
    result = []
    for value in values:
        key = round(abs(value), 6)
        if key in seen or key <= 0:
            continue
        seen.add(key)
        result.append(-key)
    return result


def _float(value: object) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _float_env(name: str, default: float) -> float:
    return _float(os.getenv(name)) or default


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
