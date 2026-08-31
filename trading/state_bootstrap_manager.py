"""Bootstrap buses from local cache, then keep REAL_IBKR subscriptions available."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trading.audit_writer import AuditWriter
from trading.config import PROJECT_ROOT
from trading.realtime_account_state_bus import RealtimeAccountStateBus


REPORT_DIR = PROJECT_ROOT / "reports" / "state_bootstrap"


class StateBootstrapManager:
    def __init__(self, bus: RealtimeAccountStateBus, audit_writer: AuditWriter | None = None) -> None:
        self.bus = bus
        self.audit_writer = audit_writer or bus.audit_writer

    def bootstrap(self, *, start_real_ibkr_subscriptions: bool = True) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        fields = [
            ("account", PROJECT_ROOT / "reports" / "account_state" / "latest.json", 5.0),
            ("position", PROJECT_ROOT / "reports" / "position_guard" / "latest.json", 5.0),
            ("quote", PROJECT_ROOT / "reports" / "quote_state" / "latest.json", 2.0),
            ("pnl", PROJECT_ROOT / "reports" / "pnl_ledger" / "latest.json", 5.0),
            ("open_order", PROJECT_ROOT / "reports" / "open_order_state" / "latest.json", 5.0),
            ("execution", PROJECT_ROOT / "reports" / "simulation_run" / "latest.json", 5.0),
        ]
        rows = []
        for field, path, threshold in fields:
            payload = read_json(path)
            source_ts = source_timestamp(path, payload)
            age = (now - source_ts).total_seconds() if source_ts else None
            status = "NO_CACHE" if not payload else "FRESH_CACHE" if age is not None and age <= threshold else "STALE_CACHE"
            if payload:
                self.bus.update(field, {**payload, "source_type": "LOCAL_CACHE", "freshness_status": status}, source_module="bootstrap_cache", stale_flag=status == "STALE_CACHE")
            row = {
                "event_id": f"bootstrap-{field}-{int(now.timestamp())}",
                "timestamp_utc": now.isoformat(),
                "field_name": field,
                "source_type": "LOCAL_CACHE" if payload else "NONE",
                "source_timestamp": source_ts.isoformat() if source_ts else "",
                "current_age_sec": age,
                "stale_threshold_sec": threshold,
                "freshness_status": status,
                "bus_status": "WAITING_FOR_REAL_IBKR" if start_real_ibkr_subscriptions else "BOOTSTRAPPED_FROM_CACHE",
                "payload_json": json.dumps({"path": str(path), "cache_loaded": bool(payload)}, sort_keys=True),
            }
            rows.append(row)
            self.audit_writer.submit("bootstrap_state_events", row)
        report = {
            "timestamp": now.isoformat(),
            "source": "state_bootstrap_manager",
            "local_cache_loaded": any(row["freshness_status"] != "NO_CACHE" for row in rows),
            "real_ibkr_subscriptions_started_after_cache": start_real_ibkr_subscriptions,
            "cache_does_not_replace_real_ibkr": True,
            "bus_status": "WAITING_FOR_REAL_IBKR" if start_real_ibkr_subscriptions else "BOOTSTRAPPED_FROM_CACHE",
            "fields": rows,
        }
        self.audit_writer.flush()
        write_report(report)
        return report


def source_timestamp(path: Path, payload: dict[str, Any]) -> datetime | None:
    for key in ("timestamp", "timestamp_utc", "created_at"):
        value = payload.get(key)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
    if path.exists():
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    return None


def write_report(payload: dict[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "latest.json").write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    (REPORT_DIR / "latest.md").write_text(
        f"# State Bootstrap\n\n- local_cache_loaded: {payload['local_cache_loaded']}\n- real_ibkr_subscriptions_started_after_cache: {payload['real_ibkr_subscriptions_started_after_cache']}\n- bus_status: {payload['bus_status']}\n",
        encoding="utf-8",
    )


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}
