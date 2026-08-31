import json
import os
from datetime import datetime, timezone
from typing import Any, Mapping

from trading.config import PROJECT_ROOT
from trading.price_normalizer import normalize_order_price
from trading.profit_lock import common_row


REPORT_DIR = PROJECT_ROOT / "reports" / "trailing_profit"
STATE_PATH = REPORT_DIR / "state.json"


def build_trailing_profit_report(position_guard: Mapping[str, Any] | None = None) -> dict[str, Any]:
    position_guard = position_guard or read_json(PROJECT_ROOT / "reports" / "position_guard" / "latest.json")
    trigger_pct = float(os.getenv("TRAILING_PROFIT_TRIGGER_PCT", "0.08"))
    trail_pct = float(os.getenv("TRAILING_PROFIT_DISTANCE_PCT", "0.04"))
    state = read_json(STATE_PATH)
    rows = []
    for row in position_guard.get("symbols", []):
        if isinstance(row, Mapping) and float(row.get("position_qty") or 0) > 0:
            rows.append(trailing_profit_row(row, state=state, trigger_pct=trigger_pct, trail_pct=trail_pct))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    report = {"timestamp": now(), "source": "trailing_profit", "report_only": True, "execution_allowed": False, "symbols": rows}
    write_report(report)
    return report


def trailing_profit_row(row: Mapping[str, Any], *, state: dict[str, Any], trigger_pct: float, trail_pct: float) -> dict[str, Any]:
    symbol = str(row.get("symbol", "")).upper()
    qty = float(row.get("position_qty") or 0)
    entry = float(row.get("avg_cost") or 0)
    price = float(row.get("market_price") or row.get("last") or 0)
    high = max(float(state.get(symbol, 0) or 0), price)
    state[symbol] = high
    pnl = (price - entry) * qty if entry and price else 0.0
    pnl_pct = (price - entry) / entry if entry else 0.0
    trigger = pnl_pct >= trigger_pct
    raw = high * (1 - trail_pct) if trigger else None
    normalized = None if raw is None else normalize_order_price(symbol=symbol, side="SELL", order_type="STP", price=raw, log=False)
    return common_row(row, "reconciled", entry, qty, price, pnl, pnl_pct, high, trigger, "trailing_stop_review" if trigger else "monitor", qty if trigger else 0, raw, normalized)


def write_report(report: Mapping[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "latest.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    lines = ["# Trailing Profit", "", "| Symbol | Trigger | High | Action | Price |", "|---|---:|---:|---|---:|"]
    for row in report.get("symbols", []):
        lines.append(f"| {row['symbol']} | {row['trigger_active']} | {row['highest_price_seen']} | {row['recommended_action']} | {row['normalized_price']} |")
    (REPORT_DIR / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_json(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()
