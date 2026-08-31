import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from trading.config import PROJECT_ROOT


REPORT_DIR = PROJECT_ROOT / "reports" / "event_risk"
LOCAL_EVENT_PATHS = (
    PROJECT_ROOT / "data" / "event_risk.json",
    PROJECT_ROOT / "reports" / "event_risk" / "local_events.json",
)


@dataclass(frozen=True)
class EventRiskConfig:
    lookahead_hours: float = 72.0
    block_new_buy: bool = True
    require_outside_rth_protection: bool = True
    require_hedge_above_notional: bool = True
    hedge_trigger_notional: float = 50_000.0
    reduce_trigger_account_loss_pct: float = 0.01
    event_multiplier: float = 1.5


def load_event_risk_config() -> EventRiskConfig:
    return EventRiskConfig(
        lookahead_hours=_float_env("EVENT_RISK_LOOKAHEAD_HOURS", 72.0),
        block_new_buy=_bool_env("EVENT_RISK_BLOCK_NEW_BUY", True),
        require_outside_rth_protection=_bool_env("EVENT_RISK_REQUIRE_OUTSIDE_RTH_PROTECTION", True),
        require_hedge_above_notional=_bool_env("EVENT_RISK_REQUIRE_HEDGE_ABOVE_NOTIONAL", True),
        hedge_trigger_notional=_float_env("EVENT_RISK_HEDGE_TRIGGER_NOTIONAL", 50_000.0),
        reduce_trigger_account_loss_pct=_float_env("EVENT_RISK_REDUCE_TRIGGER_ACCOUNT_LOSS_PCT", 0.01),
        event_multiplier=_float_env("GAP_RISK_EVENT_MULTIPLIER", 1.5),
    )


def build_event_risk_report(
    *,
    position_guard: Mapping[str, Any],
    account_net_liquidation: float | None = None,
    config: EventRiskConfig | None = None,
    local_events: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    config = config or load_event_risk_config()
    events = dict(local_events or load_local_events())
    net_liq = account_net_liquidation or _latest_net_liquidation() or 0.0
    rows = []
    for position in position_guard.get("symbols", []):
        if not isinstance(position, Mapping) or float(position.get("position_qty") or 0) <= 0:
            continue
        symbol = str(position.get("symbol", "")).upper()
        event = _event_for_symbol(events, symbol)
        notional = float(position.get("position_qty") or 0) * float(position.get("market_price") or position.get("last") or 0)
        score = float(event.get("event_risk_score", event.get("score", 0.0)) or 0.0)
        high = score >= 0.7
        base_shock = float(event.get("base_gap_shock", 0.30) or 0.30)
        adjusted_shock = min(1.0, base_shock * (config.event_multiplier if high else 1.0))
        estimated_loss_pct = (notional * adjusted_shock / net_liq) if net_liq > 0 else 0.0
        action = recommended_event_action(
            high=high,
            notional=notional,
            estimated_account_loss_pct=estimated_loss_pct,
            config=config,
        )
        rows.append(
            {
                "symbol": symbol,
                "event_risk_score": round(score, 4),
                "event_type": event.get("event_type", "none"),
                "event_time": event.get("event_time"),
                "lookahead_hours": config.lookahead_hours,
                "event_confidence": event.get("event_confidence", 0.0 if not event else 0.5),
                "event_source": event.get("event_source", "local_files" if event else "none"),
                "position_notional": round(notional, 4),
                "event_adjusted_gap_shock": round(adjusted_shock, 6),
                "block_new_buy": bool(high and config.block_new_buy),
                "require_outside_rth_protection": bool(high and config.require_outside_rth_protection),
                "require_option_hedge": bool(high and config.require_hedge_above_notional and notional >= config.hedge_trigger_notional),
                "recommended_action": action,
            }
        )
    report = {
        "timestamp": _now(),
        "source": "event_risk_control",
        "config": asdict(config),
        "symbols": rows,
        "status": "warning" if any(row["event_risk_score"] >= 0.7 for row in rows) else "ok",
    }
    write_report(report)
    return report


def recommended_event_action(*, high: bool, notional: float, estimated_account_loss_pct: float, config: EventRiskConfig) -> str:
    if not high:
        return "monitor"
    if estimated_account_loss_pct >= config.reduce_trigger_account_loss_pct:
        return "block_buy_require_outside_rth_protection_reduce_or_hedge"
    if notional >= config.hedge_trigger_notional:
        return "block_buy_require_outside_rth_protection_plan_hedge"
    return "block_buy_require_outside_rth_protection"


def load_local_events() -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for path in LOCAL_EVENT_PATHS:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            merged.update(payload.get("symbols", payload))
    return merged


def write_report(report: Mapping[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "latest.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    with (REPORT_DIR / "history.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, sort_keys=True) + "\n")


def _event_for_symbol(events: Mapping[str, Any], symbol: str) -> dict[str, Any]:
    value = events.get(symbol) or events.get(symbol.upper()) or {}
    return dict(value) if isinstance(value, Mapping) else {}


def _latest_net_liquidation() -> float | None:
    path = PROJECT_ROOT / "reports" / "account" / "latest.json"
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("net_liquidation")
        return None if value in (None, "") else float(value)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
