import unittest
from unittest.mock import patch

from trading.profit_lock import build_profit_lock_report
from trading.take_profit import build_take_profit_report
from trading.trailing_profit import build_trailing_profit_report


POSITION_GUARD = {
    "symbols": [
        {
            "symbol": "PFE",
            "position_qty": 8,
            "avg_cost": 20.0,
            "market_price": 24.0,
            "bid": 23.99,
            "ask": 24.01,
        }
    ]
}


class ProfitProtectionReportTests(unittest.TestCase):
    def test_profit_lock_take_profit_and_trailing_are_report_only(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "PROFIT_LOCK_TRIGGER_PCT": "0.05",
                "TAKE_PROFIT_TRIGGER_PCT": "0.10",
                "TRAILING_PROFIT_TRIGGER_PCT": "0.08",
            },
        ):
            reports = [
                build_profit_lock_report(POSITION_GUARD),
                build_take_profit_report(POSITION_GUARD),
                build_trailing_profit_report(POSITION_GUARD),
            ]

        for report in reports:
            self.assertTrue(report["report_only"])
            self.assertFalse(report["execution_allowed"])
            self.assertEqual(report["symbols"][0]["symbol"], "PFE")
            self.assertTrue(report["symbols"][0]["trigger_active"])
            self.assertFalse(report["symbols"][0]["execution_allowed"])


if __name__ == "__main__":
    unittest.main()
