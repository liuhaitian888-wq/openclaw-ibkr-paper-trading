import json
import os
from datetime import datetime, timezone
from typing import Any, Mapping

from trading.config import PROJECT_ROOT
from trading.price_normalizer import normalize_order_price
from trading.profit_lock import common_row


REPORT_DIR = PROJECT_ROOT / "reports" / "take_profit"


def build_take_profit_report(position_guard: Mapping[str, Any] | None = None) -> dict[str, Any]:
    position_guard = position_guard or read_json(PROJECT_ROOT / "reports" / "position_guard" / "latest.json")
    threshold = float(os.getenv("TAKE_PROFIT_TRIGGER_PCT", "0.10"))
    fraction = float(os.getenv("TAKE_PROFIT_FRACTION", "0.25"))
    rows = [take_profit_row(row, threshold=threshold, fraction=fraction) for row in position_guard.get("symbols", []) if isinstance(row, Mapping) and float(row.get("position_qty") or 0) > 0]
    report = {"timestamp": now(), "source": "take_profit", "report_only": True, "execution_allowed": False, "symbols": rows}
    write_report(report)
    return report


def take_profit_row(row: Mapping[str, Any], *, threshold: float, fraction: float) -> dict[str, Any]:
    symbol = str(row.get("symbol", "")).upper()
    qty = float(row.get("position_qty") or 0)
    entry = float(row.get("avg_cost") or 0)
    price = float(row.get("market_price") or row.get("last") or 0)
    pnl = (price - entry) * qty if entry and price else 0.0
    pnl_pct = (price - entry) / entry if entry else 0.0
    trigger = pnl_pct >= threshold
    rec_qty = min(qty, max(1, int(qty * fraction))) if trigger else 0
    raw = float(row.get("ask") or price) if trigger else None
    normalized = None if raw is None else normalize_order_price(symbol=symbol, side="SELL", order_type="LMT", price=raw, log=False)
    return common_row(row, "reconciled", entry, qty, price, pnl, pnl_pct, price, trigger, "partial_sell_lmt_plan" if trigger else "monitor", rec_qty, raw, normalized)


def write_report(report: Mapping[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "latest.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    lines = ["# Take Profit", "", "| Symbol | Trigger | Action | Qty | Price |", "|---|---:|---|---:|---:|"]
    for row in report.get("symbols", []):
        lines.append(f"| {row['symbol']} | {row['trigger_active']} | {row['recommended_action']} | {row['recommended_qty']} | {row['normalized_price']} |")
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
