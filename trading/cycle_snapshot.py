"""Immutable decision-time snapshots over the realtime account state bus."""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

from trading.audit_writer import AuditWriter
from trading.config import PROJECT_ROOT
from trading.realtime_account_state_bus import RealtimeAccountStateBus


REPORT_DIR = PROJECT_ROOT / "reports" / "cycle_snapshot"


@dataclass(frozen=True)
class CycleSnapshot:
    cycle_id: str
    snapshot_id: str
    timestamp_utc: str
    created_at: str
    trigger_event_id: str
    account_state_ref: str
    position_state_ref: str
    quote_state_ref: str
    pnl_state_ref: str
    open_order_state_ref: str
    execution_state_ref: str
    market_data_ref: str
    market_session_ref: str
    pool_state_ref: str
    news_state_ref: str
    scanner_state_ref: str
    trigger_state_ref: str
    risk_state_ref: str
    state_version_min: int
    state_version_max: int
    immutable: bool = True


def create_cycle_snapshot(
    bus: RealtimeAccountStateBus,
    *,
    cycle_id: str,
    trigger_event_id: str,
    audit_writer: AuditWriter | None = None,
) -> CycleSnapshot:
    audit_writer = audit_writer or bus.audit_writer
    versions = [
        update.state_version
        for update in [
            bus.latest_account_state,
            bus.latest_position_state,
            bus.latest_quote_state,
            bus.latest_pnl_state,
            bus.latest_open_order_state,
            bus.latest_execution_state,
            bus.latest_risk_state,
        ]
        if update is not None
    ]
    now = datetime.now(timezone.utc).isoformat()
    snapshot = CycleSnapshot(
        cycle_id=cycle_id,
        snapshot_id=f"{cycle_id}-snapshot-{max(versions) if versions else 0}",
        timestamp_utc=now,
        created_at=now,
        trigger_event_id=trigger_event_id,
        account_state_ref="realtime_account_state_bus.latest_account_state",
        position_state_ref="realtime_account_state_bus.latest_position_state",
        quote_state_ref="realtime_account_state_bus.latest_quote_state",
        pnl_state_ref="realtime_account_state_bus.latest_pnl_state",
        open_order_state_ref="realtime_account_state_bus.latest_open_order_state",
        execution_state_ref="realtime_account_state_bus.latest_execution_state",
        market_data_ref="MarketDataBus.latest_quote_state",
        market_session_ref="reports/market_session/latest.json",
        pool_state_ref="reports/pool_membership/latest.json",
        news_state_ref="reports/structured_news_events/latest.json",
        scanner_state_ref="reports/scanner_candidates/latest.json",
        trigger_state_ref="reports/fast_order_guidance/latest.json",
        risk_state_ref="realtime_account_state_bus.latest_risk_state",
        state_version_min=min(versions) if versions else 0,
        state_version_max=max(versions) if versions else 0,
    )
    payload = asdict(snapshot)
    audit_writer.submit("cycle_snapshots", {**payload, "immutable": 1, "payload_json": json.dumps(payload, sort_keys=True)})
    audit_writer.flush()
    write_report(snapshot)
    return snapshot


def write_report(snapshot: CycleSnapshot) -> dict[str, Any]:
    payload = {**asdict(snapshot), "event_driven_snapshot": True, "fixed_30_second_cycle_used_for_execution": False}
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "latest.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    (REPORT_DIR / "latest.md").write_text(
        "\n".join(
            [
                "# Cycle Snapshot",
                "",
                f"- cycle_id: {snapshot.cycle_id}",
                f"- snapshot_id: {snapshot.snapshot_id}",
                f"- trigger_event_id: {snapshot.trigger_event_id}",
                f"- state_version_min: {snapshot.state_version_min}",
                f"- state_version_max: {snapshot.state_version_max}",
                "- immutable: True",
                "- fixed_30_second_cycle_used_for_execution: False",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return payload
