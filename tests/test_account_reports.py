import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts.build_account_reports import audit_requests_for_date, daily_summary


class AccountReportsTests(unittest.TestCase):
    def test_empty_audit_database_has_no_order_requests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sqlite3.connect(root / "trading_audit.sqlite3").close()

            with patch("scripts.build_account_reports.PROJECT_ROOT", root):
                requests = audit_requests_for_date(datetime.now(timezone.utc).date())

        self.assertEqual(requests, [])

    def test_daily_summary_counts_open_orders(self) -> None:
        summary = daily_summary(
            [
                {"action": "SELL", "total_quantity": 1},
                {"action": "BUY", "total_quantity": 1},
            ]
        )
        self.assertIn("daily_order_count", summary)
        self.assertEqual(summary["open_sell_order_count"], 1)
        self.assertEqual(summary["open_buy_order_count"], 1)
        self.assertIn("daily_submitted_notional", summary)


if __name__ == "__main__":
    unittest.main()
