"""Near real-time account-centered state bus."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from trading.audit_writer import AuditWriter
from trading.config import PROJECT_ROOT


REPORT_DIR = PROJECT_ROOT / "reports" / "realtime_account_state_bus"


@dataclass(frozen=True)
class StateUpdate:
    state_version: int
    source_event_seq: int
    timestamp_utc: str
    source_module: str
    freshness_age_sec: float
    stale_flag: bool
    payload: Mapping[str, Any]


class RealtimeAccountStateBus:
    def __init__(self, audit_writer: AuditWriter | None = None) -> None:
        self.audit_writer = audit_writer or AuditWriter()
        self.state_version = 0
        self.source_event_seq = 0
        self.latest_account_state: StateUpdate | None = None
        self.latest_position_state: StateUpdate | None = None
        self.latest_quote_state: StateUpdate | None = None
        self.latest_pnl_state: StateUpdate | None = None
        self.latest_open_order_state: StateUpdate | None = None
        self.latest_execution_state: StateUpdate | None = None
        self.latest_risk_state: StateUpdate | None = None

    def update(self, state_key: str, payload: Mapping[str, Any], *, source_module: str, stale_flag: bool = False) -> StateUpdate:
        self.state_version += 1
        self.source_event_seq += 1
        now = utc_now()
        update = StateUpdate(
            state_version=self.state_version,
            source_event_seq=self.source_event_seq,
            timestamp_utc=now,
            source_module=source_module,
            freshness_age_sec=0.0,
            stale_flag=stale_flag,
            payload=dict(payload),
        )
        setattr(self, f"latest_{state_key}_state", update)
        self._archive_state_update(state_key, update)
        return update

    def snapshot_payload(self) -> dict[str, Any]:
        payload = {
            "timestamp": utc_now(),
            "source": "realtime_account_state_bus",
            "event_driven": True,
            "fixed_30_second_polling_required_for_execution": False,
            "state_version": self.state_version,
            "latest_account_state": update_to_dict(self.latest_account_state),
            "latest_position_state": update_to_dict(self.latest_position_state),
            "latest_quote_state": update_to_dict(self.latest_quote_state),
            "latest_pnl_state": update_to_dict(self.latest_pnl_state),
            "latest_open_order_state": update_to_dict(self.latest_open_order_state),
            "latest_execution_state": update_to_dict(self.latest_execution_state),
            "latest_risk_state": update_to_dict(self.latest_risk_state),
        }
        return payload

    def write_report(self) -> dict[str, Any]:
        payload = self.snapshot_payload()
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        (REPORT_DIR / "latest.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        lines = [
            "# Realtime Account State Bus",
            "",
            f"- event_driven: {payload['event_driven']}",
            f"- state_version: {payload['state_version']}",
            "- fixed_30_second_polling_required_for_execution: False",
        ]
        (REPORT_DIR / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.audit_writer.flush()
        return payload

    def _archive_state_update(self, state_key: str, update: StateUpdate) -> None:
        payload = update_to_dict(update)
        table = {
            "account": "account_state_events",
            "position": "position_state_events",
            "quote": "quote_state_events",
            "pnl": "pnl_state_events",
            "open_order": "open_order_state_events",
            "execution": "execution_state_events",
        }.get(state_key)
        if table:
            values = {
                "event_id": f"state-{state_key}-{update.source_event_seq}",
                "timestamp_utc": update.timestamp_utc,
                "state_version": update.state_version,
                "source_event_seq": update.source_event_seq,
                "source_module": update.source_module,
                "symbol": str(update.payload.get("symbol", "")),
                "bid": update.payload.get("bid"),
                "ask": update.payload.get("ask"),
                "last": update.payload.get("last"),
                "freshness_age_sec": update.freshness_age_sec,
                "stale_flag": int(update.stale_flag),
                "payload_json": json.dumps(payload, sort_keys=True),
            }
            self.audit_writer.submit(table, values)
        self.audit_writer.submit(
            "state_versions",
            {
                "state_version": update.state_version,
                "timestamp_utc": update.timestamp_utc,
                "state_key": state_key,
                "source_event_seq": update.source_event_seq,
                "source_module": update.source_module,
                "stale_flag": int(update.stale_flag),
                "payload_json": json.dumps(payload, sort_keys=True),
            },
        )


def bootstrap_bus_from_reports(audit_writer: AuditWriter | None = None) -> RealtimeAccountStateBus:
    bus = RealtimeAccountStateBus(audit_writer=audit_writer)
    bus.update("account", read_json(PROJECT_ROOT / "reports" / "account_state" / "latest.json"), source_module="bootstrap_reports")
    bus.update("position", read_json(PROJECT_ROOT / "reports" / "position_guard" / "latest.json"), source_module="bootstrap_reports")
    bus.update("quote", read_json(PROJECT_ROOT / "reports" / "quote_state" / "latest.json"), source_module="bootstrap_reports")
    bus.update("pnl", read_json(PROJECT_ROOT / "reports" / "pnl_ledger" / "latest.json"), source_module="bootstrap_reports")
    bus.update("open_order", read_json(PROJECT_ROOT / "reports" / "open_order_state" / "latest.json"), source_module="bootstrap_reports")
    bus.update("execution", read_json(PROJECT_ROOT / "reports" / "simulation_run" / "latest.json"), source_module="bootstrap_simulation")
    bus.update("risk", {"source": "risk_state", "execution_allowed": False, "live_trading_enabled": False}, source_module="bootstrap_reports")
    return bus


def update_to_dict(update: StateUpdate | None) -> dict[str, Any]:
    if update is None:
        return {}
    return asdict(update)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
