import tempfile
import unittest
from pathlib import Path

from trading.market_quote_crosscheck import classify_cross_validation_result
from trading.paper_audit_db import ensure_paper_automation_tables, sqlite_table_summary


class MarketQuoteCrosscheckTests(unittest.TestCase):
    def test_closed_market_missing_bid_ask_is_normal(self) -> None:
        result = classify_cross_validation_result(
            session_state="CLOSED",
            expected_live_bid_ask=False,
            bid_received=False,
            ask_received=False,
            last_received=True,
            live_data_confirmed=True,
            quote_blocked_reason="market_closed_no_active_bid_ask",
        )

        self.assertEqual(result, "normal_market_closed")

    def test_active_market_missing_bid_ask_is_quote_feed_problem(self) -> None:
        result = classify_cross_validation_result(
            session_state="REGULAR",
            expected_live_bid_ask=True,
            bid_received=False,
            ask_received=False,
            last_received=True,
            live_data_confirmed=True,
            quote_blocked_reason="streaming_no_bid_ask_received",
        )

        self.assertEqual(result, "quote_feed_problem")

    def test_subscription_reason_is_subscription_problem(self) -> None:
        result = classify_cross_validation_result(
            session_state="REGULAR",
            expected_live_bid_ask=True,
            bid_received=False,
            ask_received=False,
            last_received=False,
            live_data_confirmed=False,
            quote_blocked_reason="no_market_data_subscription",
        )

        self.assertEqual(result, "subscription_problem")

    def test_paper_automation_sqlite_tables_exist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "audit.sqlite3"
            ensure_paper_automation_tables(db_path)
            summary = sqlite_table_summary(db_path)

        self.assertIn("market_quote_crosscheck_events", summary)
        self.assertIn("paper_buy_events", summary)
        self.assertIn("full_paper_run_cycles", summary)
        self.assertIn("options_order_events", summary)
        self.assertIn("quote_ready", summary["paper_buy_events"]["columns"])
        self.assertIn("spread_ok", summary["paper_buy_events"]["columns"])
        self.assertIn("readback_status", summary["paper_buy_events"]["columns"])
        self.assertIn("event_type", summary["options_order_events"]["columns"])
        self.assertIn("order_submitted", summary["options_order_events"]["columns"])


if __name__ == "__main__":
    unittest.main()
