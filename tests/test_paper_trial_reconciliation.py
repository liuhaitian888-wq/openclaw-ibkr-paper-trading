import tempfile
import unittest
from pathlib import Path

from research.paper_trial_reconciliation import build_reconciliation, write_reconciliation


SUBMITTED_GATE = {
    "status": "submitted",
    "selected_symbol": "AAPL",
    "selected_payload": {
        "symbol": "AAPL",
        "side": "BUY",
        "quantity": 1,
        "limit_price": 100.0,
        "idempotency_key": "paper-aapl-0001",
    },
}


class PaperTrialReconciliationTests(unittest.TestCase):
    def test_missing_gate_is_no_paper_submission(self) -> None:
        report = build_reconciliation(None)

        self.assertEqual(report.status, "no_paper_submission")
        self.assertIsNone(report.idempotency_key)

    def test_unsubmitted_gate_is_no_paper_submission(self) -> None:
        report = build_reconciliation({"status": "blocked"})

        self.assertEqual(report.status, "no_paper_submission")

    def test_submitted_gate_reconciles_required_readbacks(self) -> None:
        report = build_reconciliation(
            SUBMITTED_GATE,
            audit_order={"order": {"status": "PAPER_LIMIT_SUBMITTED"}},
            tws_orders={
                "status": "ok",
                "open_orders": [{"order_ref": "paper-aapl-0001"}],
                "completed_orders": [],
                "executions": [],
            },
            pnl_sample={
                "timestamp": "2026-07-07T23:00:00+00:00",
                "account": "DU12345",
                "open_positions": 1,
            },
        )

        self.assertEqual(report.status, "reconciled")
        self.assertTrue(all(item.status == "pass" for item in report.items))

    def test_submitted_gate_without_tws_readback_is_incomplete(self) -> None:
        report = build_reconciliation(
            SUBMITTED_GATE,
            audit_order={"order": {"status": "PAPER_LIMIT_SUBMITTED"}},
            pnl_sample={"account": "DU12345"},
        )

        self.assertEqual(report.status, "reconciliation_incomplete")
        statuses = {item.name: item.status for item in report.items}
        self.assertEqual(statuses["tws_order_readback"], "missing")

    def test_write_reconciliation_creates_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "reconciliation.json"
            report = build_reconciliation(None)
            write_reconciliation(report, output)

            self.assertTrue(output.exists())
            self.assertIn("paper_trial_reconciliation", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
