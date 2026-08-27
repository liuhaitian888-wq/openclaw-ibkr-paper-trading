import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from tests.test_service import make_settings, valid_limit_payload
from trading.audit import AuditLog
from trading.models import TradeProposal
from trading.service import TradingService
from trading.tws_paper import BrokerSnapshot, OrderConfirmation


class ReconciliationTests(unittest.TestCase):
    def test_additive_schema_migrates_existing_audit_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.sqlite3"
            with closing(sqlite3.connect(path)) as connection:
                with connection:
                    connection.execute(
                        """
                        CREATE TABLE order_requests (
                            idempotency_key TEXT PRIMARY KEY,
                            created_at TEXT NOT NULL,
                            mode TEXT NOT NULL,
                            status TEXT NOT NULL,
                            proposal_json TEXT NOT NULL,
                            details TEXT NOT NULL
                        )
                        """
                    )

            AuditLog(path)

            with closing(sqlite3.connect(path)) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
            self.assertTrue(
                {"order_events", "broker_orders", "executions", "reconciliation_runs"}
                <= tables
            )

    def test_known_order_and_execution_are_persisted_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditLog(Path(directory) / "audit.sqlite3")
            proposal = TradeProposal("MSFT", "BUY", 1, 300.0, None, "known-order-0001")
            self.assertTrue(audit.reserve(proposal, "PAPER_LIMIT_TRANSMIT", "agent"))
            order = {
                "order_id": 200,
                "perm_id": 900,
                "order_ref": "known-order-0001",
                "symbol": "MSFT",
                "side": "BUY",
                "status": "Filled",
                "filled": 1,
                "remaining": 0,
                "completed": True,
            }
            execution = {
                "exec_id": "exec-1",
                "order_id": 200,
                "perm_id": 900,
                "order_ref": "known-order-0001",
                "symbol": "MSFT",
                "side": "BOT",
                "shares": 1,
                "price": 299.5,
                "time": "20260824 10:00:00",
            }

            first = audit.reconcile([order], [execution], [])
            second = audit.reconcile([order], [execution], [])

            self.assertEqual(first["status"], "OK")
            self.assertEqual(second["execution_count"], 1)
            with closing(sqlite3.connect(Path(directory) / "audit.sqlite3")) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM executions").fetchone()[0], 1)
                broker_row = connection.execute(
                    "SELECT is_external, canonical_status FROM broker_orders"
                ).fetchone()
                self.assertEqual(broker_row[0], 0)
                self.assertEqual(broker_row[1], "FILLED")

    def test_unknown_active_order_creates_fail_closed_block(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(
                directory,
                trading_mode="PAPER",
                allow_paper_transmit=True,
                trade_session_token="session-ok",
                max_order_value=400.0,
            )
            service = TradingService(settings)
            service._audit.reconcile(
                [
                    {
                        "order_id": 404,
                        "order_ref": "manual-tws-order",
                        "symbol": "MSFT",
                        "side": "BUY",
                        "status": "Submitted",
                        "remaining": 1,
                        "completed": False,
                    }
                ],
                [],
                [],
            )
            payload = valid_limit_payload("blocked-order-0001")
            payload["trade_session_token"] = "session-ok"

            with self.assertRaisesRegex(PermissionError, "unreconciled external"):
                service.submit_limit(payload, transmit=True)

    @patch("trading.service.TwsPaperBroker")
    def test_service_reconciliation_persists_broker_snapshot(self, broker_class: object) -> None:
        with tempfile.TemporaryDirectory() as directory:
            broker_class.return_value.collect_snapshot.return_value = BrokerSnapshot(
                orders=(
                    {
                        "order_id": 501,
                        "order_ref": "",
                        "status": "Submitted",
                        "completed": False,
                    },
                ),
                executions=(),
                messages=("readonly snapshot",),
            )
            service = TradingService(make_settings(directory))

            result = service.reconcile_orders()

            self.assertEqual(result["status"], "BLOCKED_EXTERNAL_ORDERS")
            self.assertEqual(result["external_active_count"], 1)
            self.assertEqual(result["unresolved_external_orders"][0]["order_id"], 501)
            self.assertEqual(
                service.health()["audit"]["latest_reconciliation"]["status"],
                "BLOCKED_EXTERNAL_ORDERS",
            )

    @patch("trading.service.TwsPaperBroker")
    def test_submission_records_broker_link_and_event_history(self, broker_class: object) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(
                directory,
                trading_mode="PAPER",
                allow_paper_transmit=True,
                trade_session_token="session-ok",
                max_order_value=400.0,
            )
            broker_class.return_value.submit_limit.return_value = OrderConfirmation(
                order_ids=(700,), statuses={700: "Submitted"}
            )
            payload = valid_limit_payload("linked-order-0001")
            payload["trade_session_token"] = "session-ok"
            service = TradingService(settings)

            service.submit_limit(payload, transmit=True)
            record = service.audit_order("linked-order-0001")["order"]

            self.assertEqual(
                [event["event_type"] for event in record["events"]],
                ["REQUEST_RESERVED", "REQUEST_STATUS_CHANGED", "BROKER_ORDER_LINKED"],
            )


if __name__ == "__main__":
    unittest.main()
