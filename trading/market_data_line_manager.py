import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from trading.config import PROJECT_ROOT


REPORT_PATH = PROJECT_ROOT / "reports" / "market_data_lines" / "latest.json"


@dataclass(frozen=True)
class MarketDataLineConfig:
    max_level1_streaming_symbols: int = 60
    reserve_slots_for_positions: int = 10
    reserve_slots_for_hot_pool: int = 5
    reserve_slots_for_new_events: int = 5
    reserve_slots_for_open_orders: int = 10
    max_tick_by_tick_symbols: int = 5


@dataclass(frozen=True)
class MarketDataLinePlan:
    timestamp: str
    max_level1_streaming_symbols: int
    selected_symbols: list[str]
    protected_symbols: list[str]
    hot_symbols: list[str]
    new_event_symbols: list[str]
    overflow_symbols: list[str]
    planned_usage: int
    available_slots: int
    tick_by_tick_symbols: list[str]
    policy_notes: list[str]


class MarketDataLineManager:
    def __init__(self, config: MarketDataLineConfig = MarketDataLineConfig()) -> None:
        self.config = config

    def plan(
        self,
        *,
        current_positions: Sequence[str] = (),
        open_order_symbols: Sequence[str] = (),
        hot_symbols: Sequence[str] = (),
        new_event_symbols: Sequence[str] = (),
        core_symbols: Sequence[str] = (),
    ) -> MarketDataLinePlan:
        protected = _unique([*current_positions, *open_order_symbols])
        selected = _unique([*protected, *hot_symbols, *new_event_symbols, *core_symbols])
        limit = max(0, self.config.max_level1_streaming_symbols)
        overflow = selected[limit:]
        selected = selected[:limit]
        tick = [symbol for symbol in _unique(hot_symbols) if symbol in selected][: self.config.max_tick_by_tick_symbols]
        return MarketDataLinePlan(
            timestamp=datetime.now(timezone.utc).isoformat(),
            max_level1_streaming_symbols=limit,
            selected_symbols=selected,
            protected_symbols=protected,
            hot_symbols=[symbol for symbol in _unique(hot_symbols) if symbol in selected],
            new_event_symbols=[symbol for symbol in _unique(new_event_symbols) if symbol in selected],
            overflow_symbols=overflow,
            planned_usage=len(selected),
            available_slots=max(0, limit - len(selected)),
            tick_by_tick_symbols=tick,
            policy_notes=[
                "current positions and open orders are protected and selected first",
                "low-priority core symbols are cancelled before hot or protected symbols",
                "current position monitoring is never cancelled unless explicitly forced",
                "this module is dry-run/report-only until integrated",
            ],
        )

    def write_report(self, plan: MarketDataLinePlan) -> None:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(asdict(plan), indent=2, sort_keys=True), encoding="utf-8")


def _unique(symbols: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol and symbol.strip()))
