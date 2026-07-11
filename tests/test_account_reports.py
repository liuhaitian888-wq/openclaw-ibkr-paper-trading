import unittest

from scripts.build_account_reports import daily_summary


class AccountReportsTests(unittest.TestCase):
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
