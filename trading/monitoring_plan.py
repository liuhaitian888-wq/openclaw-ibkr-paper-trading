"""Make market-data coverage explicit without silently claiming all-symbol streaming."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Sequence


@dataclass(frozen=True)
class MonitoringPlan:
    target_symbols: tuple[str, ...]
    concurrent_symbols: tuple[str, ...]
    deferred_symbols: tuple[str, ...]
    mode: str
    refresh_cycles_needed: int
    strategy_input_enabled: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_monitoring_plan(symbols: Sequence[str], *, concurrent_limit: int) -> MonitoringPlan:
    clean = tuple(dict.fromkeys(item.strip().upper() for item in symbols if item and item.strip()))
    if concurrent_limit < 1:
        raise ValueError("concurrent_limit must be positive")
    concurrent = clean[:concurrent_limit]
    deferred = clean[concurrent_limit:]
    cycles = max(1, (len(clean) + concurrent_limit - 1) // concurrent_limit)
    return MonitoringPlan(
        target_symbols=clean,
        concurrent_symbols=concurrent,
        deferred_symbols=deferred,
        mode="SIMULTANEOUS" if not deferred else "ROTATING_BATCHES",
        refresh_cycles_needed=cycles,
    )
