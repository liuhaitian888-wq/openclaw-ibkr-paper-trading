import json
import sqlite3
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from trading.models import TradeProposal


class AuditLog:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS order_requests (
                        idempotency_key TEXT PRIMARY KEY,
                        created_at TEXT NOT NULL,
                        mode TEXT NOT NULL,
                        status TEXT NOT NULL,
                        proposal_json TEXT NOT NULL,
                        details TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS order_events (
                        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        idempotency_key TEXT NOT NULL,
                        occurred_at TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        details TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_order_events_key_time
                    ON order_events (idempotency_key, occurred_at)
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS broker_orders (
                        order_id INTEGER PRIMARY KEY,
                        perm_id INTEGER NOT NULL DEFAULT 0,
                        parent_id INTEGER NOT NULL DEFAULT 0,
                        client_id INTEGER NOT NULL DEFAULT 0,
                        order_ref TEXT NOT NULL DEFAULT '',
                        account TEXT NOT NULL DEFAULT '',
                        symbol TEXT NOT NULL DEFAULT '',
                        side TEXT NOT NULL DEFAULT '',
                        order_type TEXT NOT NULL DEFAULT '',
                        quantity REAL NOT NULL DEFAULT 0,
                        limit_price REAL NOT NULL DEFAULT 0,
                        aux_price REAL NOT NULL DEFAULT 0,
                        tif TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT '',
                        canonical_status TEXT NOT NULL DEFAULT 'UNKNOWN',
                        filled REAL NOT NULL DEFAULT 0,
                        remaining REAL NOT NULL DEFAULT 0,
                        avg_fill_price REAL NOT NULL DEFAULT 0,
                        completed INTEGER NOT NULL DEFAULT 0,
                        is_external INTEGER NOT NULL DEFAULT 0,
                        first_seen_at TEXT NOT NULL,
                        last_seen_at TEXT NOT NULL,
                        raw_json TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS executions (
                        exec_id TEXT PRIMARY KEY,
                        order_id INTEGER NOT NULL,
                        perm_id INTEGER NOT NULL DEFAULT 0,
                        order_ref TEXT NOT NULL DEFAULT '',
                        account TEXT NOT NULL DEFAULT '',
                        symbol TEXT NOT NULL DEFAULT '',
                        side TEXT NOT NULL DEFAULT '',
                        shares REAL NOT NULL DEFAULT 0,
                        price REAL NOT NULL DEFAULT 0,
                        executed_at TEXT NOT NULL DEFAULT '',
                        first_seen_at TEXT NOT NULL,
                        raw_json TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS reconciliation_runs (
                        run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        started_at TEXT NOT NULL,
                        completed_at TEXT NOT NULL,
                        status TEXT NOT NULL,
                        order_count INTEGER NOT NULL,
                        execution_count INTEGER NOT NULL,
                        external_active_count INTEGER NOT NULL,
                        messages_json TEXT NOT NULL
                    )
                    """
                )
                self._ensure_column(
                    connection,
                    "broker_orders",
                    "canonical_status",
                    "TEXT NOT NULL DEFAULT 'UNKNOWN'",
                )

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {
            str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")
        }
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def reserve(self, proposal: TradeProposal, mode: str, source: str) -> bool:
        payload = json.dumps(
            {
                "symbol": proposal.symbol,
                "side": proposal.side,
                "quantity": proposal.quantity,
                "limit_price": proposal.limit_price,
                "stop_price": proposal.stop_price,
                "source": source,
            },
            sort_keys=True,
        )
        try:
            with closing(self._connect()) as connection:
                with connection:
                    created_at = datetime.now(timezone.utc).isoformat()
                    connection.execute(
                        """
                        INSERT INTO order_requests
                        (idempotency_key, created_at, mode, status, proposal_json, details)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            proposal.idempotency_key,
                            created_at,
                            mode,
                            "RESERVED",
                            payload,
                            "",
                        ),
                    )
                    self._insert_event(
                        connection,
                        proposal.idempotency_key,
                        created_at,
                        "REQUEST_RESERVED",
                        "RESERVED",
                        "",
                    )
            return True
        except sqlite3.IntegrityError:
            return False

    def update(self, idempotency_key: str, status: str, details: str) -> None:
        with closing(self._connect()) as connection:
            with connection:
                occurred_at = datetime.now(timezone.utc).isoformat()
                connection.execute(
                    """
                    UPDATE order_requests SET status = ?, details = ?
                    WHERE idempotency_key = ?
                    """,
                    (status, details, idempotency_key),
                )
                self._insert_event(
                    connection,
                    idempotency_key,
                    occurred_at,
                    "REQUEST_STATUS_CHANGED",
                    status,
                    details,
                )

    def record_submission(
        self,
        idempotency_key: str,
        order_ids: List[int],
        statuses: Dict[int, str],
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as connection:
            with connection:
                for order_id in order_ids:
                    payload = {
                        "order_id": int(order_id),
                        "order_ref": idempotency_key,
                        "status": statuses.get(order_id, ""),
                    }
                    self._upsert_broker_order(connection, payload, now, external=False)
                    self._insert_event(
                        connection,
                        idempotency_key,
                        now,
                        "BROKER_ORDER_LINKED",
                        payload["status"],
                        json.dumps(payload, sort_keys=True),
                    )

    def reconcile(
        self,
        orders: List[Dict[str, Any]],
        executions: List[Dict[str, Any]],
        messages: List[str],
    ) -> Dict[str, Any]:
        started_at = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as connection:
            with connection:
                known_refs = {
                    str(row["idempotency_key"])
                    for row in connection.execute(
                        "SELECT idempotency_key FROM order_requests"
                    ).fetchall()
                }
                for order in orders:
                    order_ref = str(order.get("order_ref", ""))
                    external = not order_ref or order_ref not in known_refs
                    self._upsert_broker_order(
                        connection, order, started_at, external=external
                    )
                    if order_ref in known_refs:
                        self._insert_event(
                            connection,
                            order_ref,
                            started_at,
                            "BROKER_RECONCILED",
                            str(order.get("status", "")),
                            json.dumps(order, sort_keys=True),
                        )
                for execution in executions:
                    self._upsert_execution(connection, execution, started_at)
                    order_ref = str(execution.get("order_ref", ""))
                    if order_ref in known_refs:
                        self._insert_event(
                            connection,
                            order_ref,
                            started_at,
                            "EXECUTION_RECORDED",
                            "FILLED",
                            json.dumps(execution, sort_keys=True),
                        )
                external_active_count = self._external_active_count(connection)
                completed_at = datetime.now(timezone.utc).isoformat()
                status = "BLOCKED_EXTERNAL_ORDERS" if external_active_count else "OK"
                connection.execute(
                    """
                    INSERT INTO reconciliation_runs
                    (started_at, completed_at, status, order_count, execution_count,
                     external_active_count, messages_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        started_at,
                        completed_at,
                        status,
                        len(orders),
                        len(executions),
                        external_active_count,
                        json.dumps(messages, sort_keys=True),
                    ),
                )
        return {
            "status": status,
            "started_at": started_at,
            "completed_at": completed_at,
            "order_count": len(orders),
            "execution_count": len(executions),
            "external_active_count": external_active_count,
            "messages": messages,
        }

    def has_unresolved_external_orders(self) -> bool:
        with closing(self._connect()) as connection:
            return self._external_active_count(connection) > 0

    def unresolved_external_orders(self) -> List[Dict[str, Any]]:
        terminal = ("Filled", "Cancelled", "ApiCancelled", "Inactive")
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT order_id, perm_id, order_ref, symbol, side, status,
                       canonical_status, filled, remaining, last_seen_at
                FROM broker_orders
                WHERE is_external = 1 AND completed = 0
                  AND status NOT IN (?, ?, ?, ?)
                ORDER BY order_id ASC
                """,
                terminal,
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_reconciliation(self) -> Optional[Dict[str, Any]]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT started_at, completed_at, status, order_count,
                       execution_count, external_active_count, messages_json
                FROM reconciliation_runs ORDER BY run_id DESC LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return {
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "status": row["status"],
            "order_count": row["order_count"],
            "execution_count": row["execution_count"],
            "external_active_count": row["external_active_count"],
            "messages": json.loads(row["messages_json"]),
        }

    def order_events(self, idempotency_key: str) -> List[Dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT event_id, occurred_at, event_type, status, details
                FROM order_events WHERE idempotency_key = ?
                ORDER BY event_id ASC
                """,
                (idempotency_key,),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _insert_event(
        connection: sqlite3.Connection,
        idempotency_key: str,
        occurred_at: str,
        event_type: str,
        status: str,
        details: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO order_events
            (idempotency_key, occurred_at, event_type, status, details)
            VALUES (?, ?, ?, ?, ?)
            """,
            (idempotency_key, occurred_at, event_type, status, details),
        )

    @staticmethod
    def _upsert_broker_order(
        connection: sqlite3.Connection,
        order: Dict[str, Any],
        seen_at: str,
        *,
        external: bool,
    ) -> None:
        values = (
            int(order.get("order_id", 0)), int(order.get("perm_id", 0)),
            int(order.get("parent_id", 0)), int(order.get("client_id", 0)),
            str(order.get("order_ref", "")), str(order.get("account", "")),
            str(order.get("symbol", "")), str(order.get("side", "")),
            str(order.get("order_type", "")), float(order.get("quantity", 0)),
            float(order.get("limit_price", 0)), float(order.get("aux_price", 0)),
            str(order.get("tif", "")), str(order.get("status", "")),
            AuditLog._canonical_order_status(order),
            float(order.get("filled", 0)), float(order.get("remaining", 0)),
            float(order.get("avg_fill_price", 0)), int(bool(order.get("completed", False))),
            int(external), seen_at, seen_at, json.dumps(order, sort_keys=True),
        )
        connection.execute(
            """
            INSERT INTO broker_orders
            (order_id, perm_id, parent_id, client_id, order_ref, account, symbol,
             side, order_type, quantity, limit_price, aux_price, tif, status, canonical_status,
             filled, remaining, avg_fill_price, completed, is_external,
             first_seen_at, last_seen_at, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(order_id) DO UPDATE SET
              perm_id=excluded.perm_id, parent_id=excluded.parent_id,
              client_id=excluded.client_id, order_ref=excluded.order_ref,
              account=excluded.account, symbol=excluded.symbol, side=excluded.side,
              order_type=excluded.order_type, quantity=excluded.quantity,
              limit_price=excluded.limit_price, aux_price=excluded.aux_price,
              tif=excluded.tif, status=excluded.status,
              canonical_status=excluded.canonical_status, filled=excluded.filled,
              remaining=excluded.remaining, avg_fill_price=excluded.avg_fill_price,
              completed=excluded.completed, is_external=excluded.is_external,
              last_seen_at=excluded.last_seen_at, raw_json=excluded.raw_json
            """,
            values,
        )

    @staticmethod
    def _canonical_order_status(order: Dict[str, Any]) -> str:
        status = str(order.get("status", ""))
        filled = float(order.get("filled", 0))
        remaining = float(order.get("remaining", 0))
        if status == "Filled" or (filled > 0 and remaining == 0):
            return "FILLED"
        if filled > 0 and remaining > 0:
            return "PARTIALLY_FILLED"
        if status in {"ApiPending", "PendingSubmit"}:
            return "PENDING_SUBMIT"
        if status in {"PreSubmitted", "Submitted"}:
            return "ACTIVE"
        if status == "PendingCancel":
            return "CANCELLATION_PENDING"
        if status in {"Cancelled", "ApiCancelled"}:
            return "CANCELLED"
        if status == "Inactive":
            return "REJECTED_OR_INACTIVE"
        return "UNKNOWN"

    @staticmethod
    def _upsert_execution(
        connection: sqlite3.Connection,
        execution: Dict[str, Any],
        seen_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO executions
            (exec_id, order_id, perm_id, order_ref, account, symbol, side, shares,
             price, executed_at, first_seen_at, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(exec_id) DO UPDATE SET raw_json=excluded.raw_json
            """,
            (
                str(execution.get("exec_id", "")), int(execution.get("order_id", 0)),
                int(execution.get("perm_id", 0)), str(execution.get("order_ref", "")),
                str(execution.get("account", "")), str(execution.get("symbol", "")),
                str(execution.get("side", "")), float(execution.get("shares", 0)),
                float(execution.get("price", 0)), str(execution.get("time", "")),
                seen_at, json.dumps(execution, sort_keys=True),
            ),
        )

    @staticmethod
    def _external_active_count(connection: sqlite3.Connection) -> int:
        terminal = ("Filled", "Cancelled", "ApiCancelled", "Inactive")
        row = connection.execute(
            """
            SELECT COUNT(*) AS count FROM broker_orders
            WHERE is_external = 1 AND completed = 0
              AND status NOT IN (?, ?, ?, ?)
            """,
            terminal,
        ).fetchone()
        return int(row["count"])

    def get(self, idempotency_key: str) -> Optional[Dict[str, Any]]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT idempotency_key, created_at, mode, status, proposal_json, details
                FROM order_requests
                WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def list_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 500))
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT idempotency_key, created_at, mode, status, proposal_json, details
                FROM order_requests
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_for_date(
        self,
        day: str,
        timezone_name: str = "Europe/Berlin",
    ) -> List[Dict[str, Any]]:
        requested_day = date.fromisoformat(day)
        try:
            zone = ZoneInfo(timezone_name)
        except Exception as exc:
            raise ValueError(f"invalid timezone: {timezone_name}") from exc

        start_local = datetime.combine(requested_day, time.min, tzinfo=zone)
        end_local = start_local + timedelta(days=1)
        start_utc = start_local.astimezone(timezone.utc).isoformat()
        end_utc = end_local.astimezone(timezone.utc).isoformat()

        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT idempotency_key, created_at, mode, status, proposal_json, details
                FROM order_requests
                WHERE created_at >= ? AND created_at < ?
                ORDER BY created_at ASC
                """,
                (start_utc, end_utc),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def paper_notional_for_date(
        self,
        day: str,
        timezone_name: str = "Europe/Berlin",
    ) -> float:
        return round(
            sum(
                _notional(record)
                for record in self.list_for_date(day, timezone_name)
                if str(record["mode"]).startswith("PAPER")
                and record["status"] != "FAILED"
            ),
            6,
        )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "idempotency_key": row["idempotency_key"],
            "created_at": row["created_at"],
            "mode": row["mode"],
            "status": row["status"],
            "proposal": json.loads(row["proposal_json"]),
            "details": row["details"],
        }


def _notional(record: Dict[str, Any]) -> float:
    proposal = record.get("proposal", {})
    if not isinstance(proposal, dict):
        return 0.0
    try:
        return float(proposal.get("quantity", 0)) * float(proposal.get("limit_price", 0.0))
    except (TypeError, ValueError):
        return 0.0
