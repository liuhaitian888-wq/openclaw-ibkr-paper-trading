"""Priority-aware market-data freshness gate for the Paper execution path.

Normal universe symbols are deliberately rotated through finite L1 capacity.
Positions, open orders, and upper-pool symbols are never allowed to inherit
that relaxed treatment: stale critical data immediately prevents new risk.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping, Sequence


@dataclass(frozen=True)
class FreshnessSla:
    min_universe_coverage_ratio: float = 0.70
    max_universe_stale_ratio: float = 0.30
    high_min_coverage_ratio: float = 0.90
    abnormal_min_coverage_ratio: float = 0.80
    normal_revisit_cycles: int = 4


def assess_universe_freshness(
    *,
    universe_symbols: Sequence[str],
    quote_rows: Sequence[Mapping[str, Any]],
    held_symbols: Sequence[str],
    open_order_symbols: Sequence[str],
    high_pool_symbols: Sequence[str],
    abnormal_symbols: Sequence[str],
    cycle: int,
    rotation_state: MutableMapping[str, int],
    pool_levels: Mapping[str, str] | None = None,
    sla: FreshnessSla = FreshnessSla(),
) -> dict[str, Any]:
    """Return a JSON-safe execution decision and update normal rotation state."""
    universe = _symbols(universe_symbols)
    fresh = {
        str(row.get("symbol") or "").upper()
        for row in quote_rows
        if bool(row.get("bid_fresh")) and bool(row.get("ask_fresh"))
    }
    priority = {
        "critical": _symbols([*held_symbols, *open_order_symbols]),
        "high": _symbols(high_pool_symbols),
        "abnormal": _symbols(abnormal_symbols),
    }
    priority["critical"] &= universe
    priority["high"] = (priority["high"] & universe) - priority["critical"]
    priority["abnormal"] = (priority["abnormal"] & universe) - priority["critical"] - priority["high"]
    priority["normal"] = universe - priority["critical"] - priority["high"] - priority["abnormal"]

    for symbol in priority["normal"] & fresh:
        rotation_state[symbol] = cycle
    overdue_normal = sorted(
        symbol for symbol in priority["normal"]
        if cycle - int(rotation_state.get(symbol, -sla.normal_revisit_cycles - 1)) > sla.normal_revisit_cycles
    )

    def metrics(symbols: set[str]) -> dict[str, Any]:
        total = len(symbols)
        fresh_count = len(symbols & fresh)
        return {
            "symbols": sorted(symbols), "total": total, "fresh": fresh_count,
            "stale": total - fresh_count,
            "coverage_ratio": 1.0 if total == 0 else fresh_count / total,
        }

    by_priority = {name: metrics(symbols) for name, symbols in priority.items()}
    row_by_symbol = {str(row.get("symbol") or "").upper(): dict(row) for row in quote_rows}
    priority_by_symbol = {
        symbol: name for name, symbols in priority.items() for symbol in symbols
    }
    total = len(universe)
    fresh_count = len(universe & fresh)
    coverage_ratio = 1.0 if total == 0 else fresh_count / total
    stale_ratio = 0.0 if total == 0 else 1.0 - coverage_ratio
    reasons: list[str] = []
    if by_priority["critical"]["stale"]:
        reasons.append("critical_symbol_stale")
    if by_priority["high"]["coverage_ratio"] < sla.high_min_coverage_ratio:
        reasons.append("high_pool_coverage_below_sla")
    if by_priority["abnormal"]["coverage_ratio"] < sla.abnormal_min_coverage_ratio:
        reasons.append("abnormal_symbol_coverage_below_sla")
    if coverage_ratio < sla.min_universe_coverage_ratio:
        reasons.append("universe_coverage_below_sla")
    if stale_ratio > sla.max_universe_stale_ratio:
        reasons.append("universe_stale_ratio_above_sla")
    if overdue_normal:
        reasons.append("normal_rotation_window_exceeded")
    return {
        "safe_mode": bool(reasons),
        "execution_allowed": not reasons,
        "blocked_reason": ";".join(reasons),
        "coverage_ratio": coverage_ratio,
        "stale_ratio": stale_ratio,
        "fresh_count": fresh_count,
        "stale_count": total - fresh_count,
        "universe_count": total,
        "by_priority": by_priority,
        "symbol_details": [
            {
                "symbol": symbol,
                "priority": priority_by_symbol[symbol],
                "pool_level": (pool_levels or {}).get(symbol, "UNKNOWN"),
                "fresh": symbol in fresh,
                "subscription_status": row_by_symbol.get(symbol, {}).get("subscription_status", "ROTATED_OUT"),
                "stale_reason": row_by_symbol.get(symbol, {}).get("stale_reason", "rotation_inactive"),
                "rotation_state": row_by_symbol.get(symbol, {}).get("rotation_state", "ROTATED_OUT"),
                "last_covered_cycle": rotation_state.get(symbol),
                "bid_timestamp": row_by_symbol.get(symbol, {}).get("bid_timestamp", ""),
                "ask_timestamp": row_by_symbol.get(symbol, {}).get("ask_timestamp", ""),
                "last_timestamp": row_by_symbol.get(symbol, {}).get("last_timestamp", ""),
                "last_callback_timestamp": row_by_symbol.get(symbol, {}).get("last_callback_timestamp", ""),
                "bid_age_ms": row_by_symbol.get(symbol, {}).get("bid_age_ms"),
                "ask_age_ms": row_by_symbol.get(symbol, {}).get("ask_age_ms"),
                "last_age_ms": row_by_symbol.get(symbol, {}).get("last_age_ms"),
                "callback_age_ms": row_by_symbol.get(symbol, {}).get("callback_age_ms"),
            }
            for symbol in sorted(universe)
        ],
        "rotation": {
            "cycle": cycle,
            "normal_revisit_cycles": sla.normal_revisit_cycles,
            "overdue_symbols": overdue_normal,
            "overdue_count": len(overdue_normal),
        },
        "sla": {
            "min_universe_coverage_ratio": sla.min_universe_coverage_ratio,
            "max_universe_stale_ratio": sla.max_universe_stale_ratio,
            "high_min_coverage_ratio": sla.high_min_coverage_ratio,
            "abnormal_min_coverage_ratio": sla.abnormal_min_coverage_ratio,
        },
    }


def _symbols(values: Sequence[str]) -> set[str]:
    return {str(value).upper() for value in values if str(value).strip()}
