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
                    connection.execute(
                        """
                        INSERT INTO order_requests
                        (idempotency_key, created_at, mode, status, proposal_json, details)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            proposal.idempotency_key,
                            datetime.now(timezone.utc).isoformat(),
                            mode,
                            "RESERVED",
                            payload,
                            "",
                        ),
                    )
            return True
        except sqlite3.IntegrityError:
            return False

    def update(self, idempotency_key: str, status: str, details: str) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    UPDATE order_requests SET status = ?, details = ?
                    WHERE idempotency_key = ?
                    """,
                    (status, details, idempotency_key),
                )

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
