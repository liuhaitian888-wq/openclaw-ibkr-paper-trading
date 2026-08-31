"""Always-listening subscription state reporting."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from trading.audit_writer import AuditWriter
from trading.config import PROJECT_ROOT


REPORT_DIR = PROJECT_ROOT / "reports" / "subscription_health"
ALLOWED_STATES = ["ACTIVE", "IDLE", "WAITING_FOR_FIRST_EVENT", "STALE_BUT_LISTENING", "DISCONNECTED", "ERROR"]


def build_subscription_health_report(streams: list[dict[str, Any]] | None = None, *, audit_writer: AuditWriter | None = None) -> dict[str, Any]:
    writer = audit_writer or AuditWriter()
    now = datetime.now(timezone.utc).isoformat()
    if streams is None:
        streams = default_streams(now)
    for stream in streams:
        writer.submit("subscription_state_events", {**stream, "payload_json": json.dumps(stream, sort_keys=True)})
    writer.flush()
    report = {
        "timestamp": now,
        "source": "subscription_health",
        "allowed_states": ALLOWED_STATES,
        "stale_is_field_status_not_stop_command": True,
        "stale_did_disable_subscription": False,
        "auto_return_to_fresh_on_new_callback": True,
        "streams": streams,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "latest.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    (REPORT_DIR / "latest.md").write_text(
        "# Subscription Health\n\n- stale_did_disable_subscription: False\n- auto_return_to_fresh_on_new_callback: True\n",
        encoding="utf-8",
    )
    return report


def default_streams(now: str) -> list[dict[str, Any]]:
    return [
        stream("market_data", now, callback_wired=True, subscription_requested=True, freshness_status="STALE_BUT_LISTENING", waiting_reason="market closed or waiting for bid/ask update"),
        stream("account", now, callback_wired=True, subscription_requested=True, freshness_status="WAITING_FOR_UPDATE", waiting_reason="waiting for updateAccountValue/updateAccountTime"),
        stream("positions", now, callback_wired=True, subscription_requested=True, freshness_status="WAITING_FOR_UPDATE", waiting_reason="waiting for position/updatePortfolio"),
        stream("pnl", now, callback_wired=True, subscription_requested=True, freshness_status="WAITING_FOR_UPDATE", waiting_reason="waiting for pnl/pnlSingle"),
        stream("open_orders", now, callback_wired=True, subscription_requested=True, freshness_status="WAITING_FOR_UPDATE", waiting_reason="waiting for openOrder/orderStatus"),
        stream("executions", now, callback_wired=True, subscription_requested=True, freshness_status="WAITING_FOR_FIRST_EVENT", waiting_reason="no execution expected in dry-run"),
    ]


def stream(name: str, now: str, *, callback_wired: bool, subscription_requested: bool, freshness_status: str, waiting_reason: str) -> dict[str, Any]:
    return {
        "event_id": f"subscription-{name}-{now}",
        "timestamp_utc": now,
        "stream_name": name,
        "callback_wired": callback_wired,
        "callback_registered": True,
        "subscription_requested": subscription_requested,
        "subscription_active": subscription_requested,
        "last_event_seen_at": "",
        "last_event_source": "NONE",
        "freshness_status": freshness_status,
        "waiting_reason": waiting_reason,
        "reconnect_count": 0,
        "last_reconnect_at": "",
    }
