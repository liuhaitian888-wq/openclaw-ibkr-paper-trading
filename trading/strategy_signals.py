"""Strategy signal only architecture."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from trading.audit_writer import AuditWriter
from trading.config import PROJECT_ROOT


REPORT_DIR = PROJECT_ROOT / "reports" / "strategy_signals"


@dataclass(frozen=True)
class StrategySignal:
    signal_id: str
    timestamp_utc: str
    cycle_id: str
    snapshot_id: str
    symbol: str
    signal_type: str
    direction: str
    source_module: str
    source_reason: str
    confidence: float
    urgency: str
    score: float
    linked_pool_ref: str
    linked_news_ref: str
    linked_scanner_ref: str
    linked_position_ref: str
    linked_pnl_ref: str
    blocked_reason: str = ""


def create_strategy_signal(
    *,
    cycle_id: str,
    snapshot_id: str,
    symbol: str,
    direction: str,
    source_reason: str,
    audit_writer: AuditWriter | None = None,
) -> StrategySignal:
    signal = StrategySignal(
        signal_id=f"{cycle_id}-signal-{symbol.lower()}-{direction.lower()}",
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        cycle_id=cycle_id,
        snapshot_id=snapshot_id,
        symbol=symbol,
        signal_type="LOCAL_SIMULATION_SIGNAL",
        direction=direction,
        source_module="strategy_signals",
        source_reason=source_reason,
        confidence=0.7,
        urgency="MEDIUM",
        score=70.0,
        linked_pool_ref="reports/pool_membership/latest.json",
        linked_news_ref="reports/structured_news_events/latest.json",
        linked_scanner_ref="reports/scanner_candidates/latest.json",
        linked_position_ref="reports/position_guard/latest.json",
        linked_pnl_ref="reports/pnl_ledger/latest.json",
    )
    writer = audit_writer or AuditWriter()
    payload = asdict(signal)
    writer.submit("strategy_signals", {**payload, "payload_json": json.dumps(payload, sort_keys=True)})
    writer.flush()
    write_report([signal])
    return signal


def write_report(signals: list[StrategySignal]) -> dict[str, Any]:
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "strategy_signals",
        "strategy_signal_only": True,
        "strategies_can_submit_orders": False,
        "signals": [asdict(signal) for signal in signals],
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "latest.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    (REPORT_DIR / "latest.md").write_text(
        "# Strategy Signals\n\n- strategy_signal_only: True\n- strategies_can_submit_orders: False\n",
        encoding="utf-8",
    )
    return payload


def submit_order(*_args: Any, **_kwargs: Any) -> None:
    raise RuntimeError("strategies may only emit StrategySignal; submit_order is forbidden")
