import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.generate_weekly_trading_report import collect_weekly_report, render_markdown


class WeeklyTradingReportTests(unittest.TestCase):
    def test_collects_required_weekly_sections_without_account_identifier(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "reports/autonomous_agent").mkdir(parents=True)
            (root / "reports/streaming_quote_diagnostics").mkdir(parents=True)
            (root / "reports/ibkr_scanner").mkdir(parents=True)
            (root / "reports/account_state").mkdir(parents=True)
            (root / "reports/paper_execution_gate").mkdir(parents=True)
            (root / "reports/position_guard").mkdir(parents=True)
            (root / "reports/autonomous_agent/cycles.jsonl").write_text(
                "\n".join([
                    json.dumps({"created_at": "2026-09-01T00:00:00+00:00", "lifecycle_state": "SAFE_MODE"}),
                    json.dumps({"created_at": "2026-09-01T01:00:00+00:00", "lifecycle_state": "PAPER_READY"}),
                    json.dumps({"created_at": "2026-09-01T03:00:00+00:00", "lifecycle_state": "SAFE_MODE"}),
                ]), encoding="utf-8"
            )
            self._write_json(root / "reports/streaming_quote_diagnostics/latest.json", {"rows": [{"has_bid": True, "has_ask": True}, {"has_bid": True, "has_ask": False}], "errors": []})
            self._write_json(root / "reports/ibkr_scanner/latest.json", {"status": "OK", "candidate_count": 4})
            self._write_json(root / "reports/account_state/latest.json", {"account_id": "DU-SECRET", "mode": "PAPER", "state_stale": False, "positions": [{"symbol": "AAPL"}], "open_orders": [], "blocked_reason": ""})
            self._write_json(root / "reports/position_guard/latest.json", {"account": "DU-SECRET", "symbols": [{"symbol": "MSFT"}], "open_orders": [{"order_id": 1}]})
            self._write_json(root / "reports/autonomous_agent/latest.json", {"blocked_reason": "fresh quotes required"})
            self._write_json(root / "reports/paper_execution_gate/latest.json", {"blocked_reason": "risk approval required"})
            db = root / "audit.sqlite3"
            self._create_database(db)

            report = collect_weekly_report(root, db, datetime(2026, 9, 4, tzinfo=timezone.utc))

            self.assertEqual(report["orders_and_fills"]["requests"], 1)
            self.assertEqual(report["orders_and_fills"]["executions"], 1)
            self.assertEqual(report["lifecycle"]["safe_mode_seconds"], 3600)
            self.assertEqual(report["lifecycle"]["paper_ready_seconds"], 7200)
            self.assertEqual(report["scanner_and_l1"]["l1_symbols_with_fresh_bid_ask"], 1)
            self.assertNotIn("DU-SECRET", json.dumps(report))
            markdown = render_markdown(report)
            self.assertIn("Strategy and PnL", markdown)
            self.assertIn("Remaining blockers", markdown)

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload), encoding="utf-8")

    @staticmethod
    def _create_database(path: Path) -> None:
        con = sqlite3.connect(path)
        schemas = {
            "strategy_decisions": "timestamp TEXT",
            "order_requests": "created_at TEXT",
            "broker_orders": "first_seen_at TEXT",
            "executions": "executed_at TEXT",
            "risk_events": "timestamp TEXT",
            "ibkr_error_events": "timestamp_utc TEXT",
            "quote_readiness_events": "timestamp TEXT, execution_allowed INTEGER",
            "ibkr_scanner_runs": "timestamp TEXT, candidates_count INTEGER",
            "daily_pnl_summary": "pnl_sample_time_utc TEXT, daily_pnl REAL, realized_pnl REAL, unrealized_pnl REAL",
            "pnl_state_events": "timestamp_utc TEXT, stale_flag INTEGER, payload_json TEXT",
        }
        for table, columns in schemas.items():
            con.execute(f"CREATE TABLE {table} ({columns})")
        stamp = "2026-09-02T00:00:00+00:00"
        for table, column in (("strategy_decisions", "timestamp"), ("order_requests", "created_at"), ("broker_orders", "first_seen_at"), ("executions", "executed_at"), ("risk_events", "timestamp"), ("ibkr_error_events", "timestamp_utc")):
            con.execute(f"INSERT INTO {table} ({column}) VALUES (?)", (stamp,))
        con.execute("INSERT INTO quote_readiness_events VALUES (?, 0)", (stamp,))
        con.execute("INSERT INTO ibkr_scanner_runs VALUES (?, 7)", (stamp,))
        con.execute("INSERT INTO daily_pnl_summary VALUES (?, 3.0, 1.0, 2.0)", (stamp,))
        con.commit()
        con.close()


if __name__ == "__main__":
    unittest.main()
