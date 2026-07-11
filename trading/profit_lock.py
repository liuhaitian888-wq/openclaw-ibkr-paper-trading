import json
import os
from datetime import datetime, timezone
from typing import Any, Mapping

from trading.config import PROJECT_ROOT
from trading.price_normalizer import normalize_order_price


REPORT_DIR = PROJECT_ROOT / "reports" / "profit_lock"


def build_profit_lock_report(position_guard: Mapping[str, Any] | None = None) -> dict[str, Any]:
    position_guard = position_guard or read_json(PROJECT_ROOT / "reports" / "position_guard" / "latest.json")
    threshold = float(os.getenv("PROFIT_LOCK_TRIGGER_PCT", "0.05"))
    rows = [profit_lock_row(row, threshold=threshold) for row in position_guard.get("symbols", []) if isinstance(row, Mapping) and float(row.get("position_qty") or 0) > 0]
    report = {"timestamp": now(), "source": "profit_lock", "report_only": True, "execution_allowed": False, "symbols": rows}
    write_report(report, "Profit Lock")
    return report


def profit_lock_row(row: Mapping[str, Any], *, threshold: float) -> dict[str, Any]:
    symbol = str(row.get("symbol", "")).upper()
    qty = float(row.get("position_qty") or 0)
    entry = float(row.get("avg_cost") or 0)
    price = float(row.get("market_price") or row.get("last") or 0)
    pnl = (price - entry) * qty if entry and price else 0.0
    pnl_pct = (price - entry) / entry if entry else 0.0
    trigger = pnl_pct >= threshold
    raw = entry * 1.002 if trigger else None
    normalized = None if raw is None else normalize_order_price(symbol=symbol, side="SELL", order_type="STP", price=raw, log=False)
    return common_row(row, "reconciled", entry, qty, price, pnl, pnl_pct, price, trigger, "move_protection_toward_breakeven" if trigger else "monitor", qty if trigger else 0, raw, normalized)


def common_row(row: Mapping[str, Any], lot_id: str, entry: float, qty: float, price: float, pnl: float, pnl_pct: float, high: float, trigger: bool, action: str, rec_qty: float, raw: float | None, normalized: float | None) -> dict[str, Any]:
    return {
        "symbol": str(row.get("symbol", "")).upper(),
        "lot_id": f"{lot_id}-{row.get('symbol')}",
        "entry_price": entry,
        "quantity_remaining": qty,
        "market_price": price,
        "bid": row.get("bid"),
        "ask": row.get("ask"),
        "unrealized_pnl": round(pnl, 4),
        "unrealized_pnl_pct": round(pnl_pct, 6),
        "highest_price_seen": high,
        "trigger_active": trigger,
        "recommended_action": action,
        "recommended_qty": min(qty, rec_qty),
        "raw_price": raw,
        "normalized_price": normalized,
        "report_only": True,
        "execution_allowed": False,
        "blocked_reason": "report-only; no order submission",
    }


def write_report(report: Mapping[str, Any], title: str) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "latest.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    lines = [f"# {title}", "", "| Symbol | Trigger | Action | Qty | Price |", "|---|---:|---|---:|---:|"]
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
