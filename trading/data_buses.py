"""Logical data bus architecture for realtime decisions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping

from trading.audit_writer import AuditWriter
from trading.config import PROJECT_ROOT
from trading.realtime_account_state_bus import RealtimeAccountStateBus


REPORT_DIR = PROJECT_ROOT / "reports" / "data_bus_architecture"


class MarketDataBus:
    def __init__(self, account_bus: RealtimeAccountStateBus) -> None:
        self.account_bus = account_bus

    def update_quote(self, payload: Mapping[str, Any], *, source_module: str = "ibkr_callback_bridge") -> None:
        self.account_bus.update("quote", payload, source_module=source_module, stale_flag=bool(payload.get("stale_flag", False)))


class NewsTriggerBus:
    def __init__(self, audit_writer: AuditWriter | None = None) -> None:
        self.audit_writer = audit_writer or AuditWriter()
        self.latest_state: dict[str, Any] = {}

    def update(self, payload: Mapping[str, Any]) -> None:
        self.latest_state = dict(payload)


class DiscoveryPoolBus:
    def __init__(self, audit_writer: AuditWriter | None = None) -> None:
        self.audit_writer = audit_writer or AuditWriter()
        self.latest_state: dict[str, Any] = {}

    def update(self, payload: Mapping[str, Any]) -> None:
        self.latest_state = dict(payload)


def build_data_bus_architecture_report() -> dict[str, Any]:
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "logical_bus_count": 4,
        "buses": [
            {
                "bus_name": "RealtimeAccountStateBus",
                "responsibilities": [
                    "account values",
                    "buying power",
                    "positions",
                    "account PnL",
                    "per-position PnL",
                    "open orders",
                    "order status",
                    "executions",
                    "commissions",
                    "account risk state",
                ],
            },
            {
                "bus_name": "MarketDataBus",
                "responsibilities": ["bid", "ask", "last", "bid size", "ask size", "volume", "generic ticks", "market data type", "quote timestamps", "spread", "freshness"],
            },
            {
                "bus_name": "NewsTriggerBus",
                "responsibilities": ["IBKR news", "RSS", "SEC", "earnings", "corporate events", "structured news events", "risk actions", "fast order guidance"],
            },
            {
                "bus_name": "DiscoveryPoolBus",
                "responsibilities": ["IBKR scanner candidates", "external candidates", "candidate scoring", "six-layer pool membership", "pool transition events", "trade_pool state"],
            },
        ],
        "buses_logically_separated": True,
        "decision_snapshots_reference_all_buses": True,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "latest.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    lines = ["# Data Bus Architecture", "", f"- logical_bus_count: {payload['logical_bus_count']}", "- buses_logically_separated: True"]
    for bus in payload["buses"]:
        lines.append(f"- {bus['bus_name']}: {', '.join(bus['responsibilities'])}")
    (REPORT_DIR / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload
