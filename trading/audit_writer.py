"""Single-writer audit queue for SQLite append-only ledgers."""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from trading.sqlite_event_store import SQLiteEventStore


@dataclass(frozen=True)
class AuditEvent:
    table: str
    values: Mapping[str, Any]


class AuditWriter:
    """Synchronous single-writer queue.

    The queue is intentionally simple for local Mode 9 runs: modules enqueue
    events, then flush through one SQLite connection/transaction.
    """

    def __init__(self, store: SQLiteEventStore | None = None) -> None:
        self.store = store or SQLiteEventStore()
        self._queue: deque[AuditEvent] = deque()
        self.flush_count = 0

    def submit(self, table: str, values: Mapping[str, Any]) -> None:
        self._queue.append(AuditEvent(table, dict(values)))

    def submit_event_store(
        self,
        *,
        event_id: str,
        source_module: str,
        event_type: str,
        cycle_id: str = "",
        snapshot_id: str = "",
        symbol: str = "",
        state_version: int = 0,
        payload: Mapping[str, Any] | None = None,
        report_path: str = "",
    ) -> None:
        payload = dict(payload or {})
        self.submit(
            "event_store",
            {
                "event_id": event_id,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "cycle_id": cycle_id,
                "snapshot_id": snapshot_id,
                "source_module": source_module,
                "event_type": event_type,
                "symbol": symbol,
                "state_version": state_version,
                "payload_json": json.dumps(payload, sort_keys=True),
                "report_path": report_path,
            },
        )

    def flush(self) -> int:
        events = [(event.table, event.values) for event in self._queue]
        self._queue.clear()
        if events:
            self.store.append_many(events)
            self.flush_count += 1
        return len(events)

    @property
    def queued_count(self) -> int:
        return len(self._queue)
