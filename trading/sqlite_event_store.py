"""Append-only SQLite event store with WAL enabled."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping, Sequence

from trading.paper_audit_db import DB_PATH, ensure_paper_automation_tables, insert_event


class SQLiteEventStore:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        ensure_paper_automation_tables(db_path)
        self.enable_wal()

    def enable_wal(self) -> str:
        with sqlite3.connect(self.db_path) as con:
            return str(con.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower()

    def journal_mode(self) -> str:
        with sqlite3.connect(self.db_path) as con:
            return str(con.execute("PRAGMA journal_mode").fetchone()[0]).lower()

    def append(self, table: str, values: Mapping[str, Any]) -> None:
        insert_event(table, values, db_path=self.db_path)

    def append_many(self, events: Sequence[tuple[str, Mapping[str, Any]]]) -> None:
        ensure_paper_automation_tables(self.db_path)
        self.enable_wal()
        with sqlite3.connect(self.db_path) as con:
            con.execute("BEGIN")
            for table, values in events:
                self._insert_with_connection(con, table, values)
            con.commit()

    def _insert_with_connection(self, con: sqlite3.Connection, table: str, values: Mapping[str, Any]) -> None:
        from trading.paper_audit_db import PAPER_AUTOMATION_TABLES

        columns = [part.strip().split()[0] for part in PAPER_AUTOMATION_TABLES[table].split(",")]
        row = {column: values.get(column) for column in columns}
        if "payload_json" in row and row["payload_json"] is None:
            row["payload_json"] = json.dumps(dict(values), sort_keys=True)
        placeholders = ", ".join("?" for _ in columns)
        con.execute(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
            [row.get(column) for column in columns],
        )
