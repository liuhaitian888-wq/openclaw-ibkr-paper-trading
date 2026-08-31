import unittest

from trading.ibkr_callback_wiring_audit import build_ibkr_callback_wiring_audit
from trading.realtime_account_sync import run_realtime_account_sync


class IbkrCallbackWiringAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        run_realtime_account_sync("callback-audit-test")

    def test_report_distinguishes_callback_registration_from_freshness(self) -> None:
        report = build_ibkr_callback_wiring_audit()

        self.assertIn("callbacks_registered", report)
        self.assertIn("quote_execution_ready", report)
        self.assertIn("ask_fresh", report)
        self.assertIn("market_data_callbacks_wired", report)
        self.assertTrue(report["callbacks_registered"])

    def test_report_distinguishes_real_ibkr_simulation_fixture_and_none_sources(self) -> None:
        report = build_ibkr_callback_wiring_audit()

        self.assertIn("REAL_IBKR", report["last_event_source_categories"])
        self.assertIn("SIMULATION", report["last_event_source_categories"])
        self.assertIn("TEST_FIXTURE", report["last_event_source_categories"])
        self.assertIn("NONE", report["last_event_source_categories"])
        self.assertTrue(any(row["last_event_source"] == "SIMULATION" for row in report["bus_state_sources"]))
        self.assertTrue(all(row["last_event_source"] in report["last_event_source_categories"] for row in report["callback_wiring"]))

    def test_stale_ask_does_not_mark_bus_failed(self) -> None:
        report = build_ibkr_callback_wiring_audit()

        self.assertTrue(report["bus_ok"])
        if not report["ask_fresh"]:
            self.assertEqual(report["blocked_reason"], "stale_ask_or_market_closed")

    def test_stale_ask_blocks_real_paper_buy_but_not_local_simulation(self) -> None:
        report = build_ibkr_callback_wiring_audit()
        explanation = report["stale_ask_explanation"]

        self.assertTrue(explanation["blocks_real_paper_buy_execution"])
        self.assertFalse(explanation["blocks_local_simulation"])
        self.assertTrue(explanation["does_not_mean_callback_failure"])

    def test_safety_flags_remain_zero_or_false(self) -> None:
        report = build_ibkr_callback_wiring_audit()
        safety = report["strict_safety"]

        self.assertFalse(safety["paid_snapshot_used"])
        self.assertFalse(safety["regulatory_snapshot_used"])
        self.assertFalse(safety["market_order_used"])
        self.assertEqual(safety["ibkr_paper_orders_submitted"], 0)
        self.assertEqual(safety["live_orders_submitted"], 0)
        self.assertEqual(safety["orders_cancelled"], 0)


if __name__ == "__main__":
    unittest.main()
