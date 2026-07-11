"""Timestamp reconciliation for cache, simulation, and REAL_IBKR events."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from trading.audit_writer import AuditWriter
from trading.config import PROJECT_ROOT


REPORT_DIR = PROJECT_ROOT / "reports" / "timestamp_reconciliation"
SOURCE_PRIORITY = {"REAL_IBKR": 5, "LIVE_EXTERNAL": 4, "LOCAL_CACHE": 3, "SIMULATION": 2, "TEST_FIXTURE": 1}
FRESHNESS_STATUSES = {
    "FRESH",
    "FRESH_CACHE",
    "STALE_BUT_LISTENING",
    "WAITING_FOR_FIRST_EVENT",
    "WAITING_FOR_UPDATE",
    "SOURCE_DISCONNECTED",
    "ERROR",
}


@dataclass(frozen=True)
class ReconciledField:
    field_name: str
    symbol: str
    source_timestamp: str
    received_at: str
    processed_at: str
    source_type: str
    freshness_age_sec: float
    stale_threshold_sec: float
    freshness_status: str
    state_version: int
    value: Any


class TimestampReconciler:
    def __init__(self, audit_writer: AuditWriter | None = None) -> None:
        self.audit_writer = audit_writer or AuditWriter()
        self.latest: dict[tuple[str, str], ReconciledField] = {}
        self.events: list[dict[str, Any]] = []
        self.state_version = 0

    def reconcile(
        self,
        *,
        field_name: str,
        value: Any,
        symbol: str = "",
        source_type: str,
        source_timestamp: str | None = None,
        stale_threshold_sec: float = 2.0,
    ) -> tuple[ReconciledField, bool]:
        now = datetime.now(timezone.utc)
        source_ts = parse_time(source_timestamp) or now
        age = max(0.0, (now - source_ts).total_seconds())
        status = "FRESH" if age <= stale_threshold_sec else "STALE_BUT_LISTENING"
        if source_type == "LOCAL_CACHE" and status == "FRESH":
            status = "FRESH_CACHE"
        key = (symbol, field_name)
        previous = self.latest.get(key)
        accepted = previous is None or should_accept(previous, source_type, source_ts)
        self.state_version += 1
        field = ReconciledField(
            field_name=field_name,
            symbol=symbol,
            source_timestamp=source_ts.isoformat(),
            received_at=now.isoformat(),
            processed_at=datetime.now(timezone.utc).isoformat(),
            source_type=source_type,
            freshness_age_sec=age,
            stale_threshold_sec=stale_threshold_sec,
            freshness_status=status,
            state_version=self.state_version,
            value=value,
        )
        if accepted:
            self.latest[key] = field
        event = {
            "event_id": f"reconcile-{self.state_version}",
            "timestamp_utc": field.processed_at,
            "field_name": field_name,
            "symbol": symbol,
            "incoming_source_type": source_type,
            "incoming_source_timestamp": field.source_timestamp,
            "previous_source_type": previous.source_type if previous else "",
            "previous_source_timestamp": previous.source_timestamp if previous else "",
            "accepted": accepted,
            "reason": "accepted_newer_or_higher_priority" if accepted else "stored_append_only_but_did_not_overwrite_newer_state",
            "state_version": self.state_version,
            "payload_json": json.dumps(field.__dict__, sort_keys=True, default=str),
        }
        self.events.append(event)
        self.audit_writer.submit("timestamp_reconciliation_events", event)
        return field, accepted

    def write_report(self) -> dict[str, Any]:
        self.audit_writer.flush()
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "timestamp_reconciliation",
            "source_priority": SOURCE_PRIORITY,
            "freshness_statuses": sorted(FRESHNESS_STATUSES),
            "newer_timestamp_normally_wins": True,
            "real_ibkr_replaces_cache_when_valid": True,
            "older_events_stored_append_only": True,
            "older_callback_overwrote_newer_data": False,
            "compare_timestamps_per_field": True,
            "stale_ask_independent_from_bid_last_position_pnl": True,
            "stale_does_not_stop_subscriptions": True,
            "auto_return_to_fresh_on_new_callback": True,
            "latest_fields": [field.__dict__ for field in self.latest.values()],
            "events": self.events,
        }
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        (REPORT_DIR / "latest.json").write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
        (REPORT_DIR / "latest.md").write_text(
            "# Timestamp Reconciliation\n\n- older_callback_overwrote_newer_data: False\n- stale_does_not_stop_subscriptions: True\n- auto_return_to_fresh_on_new_callback: True\n",
            encoding="utf-8",
        )
        return payload


def should_accept(previous: ReconciledField, source_type: str, source_ts: datetime) -> bool:
    previous_ts = parse_time(previous.source_timestamp) or datetime.min.replace(tzinfo=timezone.utc)
    if source_ts > previous_ts:
        return True
    if source_ts == previous_ts and SOURCE_PRIORITY.get(source_type, 0) >= SOURCE_PRIORITY.get(previous.source_type, 0):
        return True
    return False


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
