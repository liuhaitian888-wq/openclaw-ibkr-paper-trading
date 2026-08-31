import json
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.build_market_data_billing_safety import build_report
from trading.account_state_manager import build_force_refresh_dry_run, quote_execution_readiness, quote_state_from_guard
from trading.ibkr_readonly import IbkrReadOnlyQuoteSource


class MarketDataBillingSafetyTests(unittest.TestCase):
    def test_snapshot_true_is_blocked_for_automatic_quote_acquisition(self) -> None:
        source = IbkrReadOnlyQuoteSource(snapshot=True)

        with patch.dict("os.environ", {"NO_PAID_MARKET_DATA_REQUESTS": "true", "ALLOW_SNAPSHOT_MARKET_DATA": "false"}):
            quotes = source.get_quotes(["AAPL"])

        self.assertEqual(quotes, [])
        self.assertIn("snapshot market data request blocked", source.last_errors[0])

    def test_missing_quote_does_not_trigger_paid_or_regulatory_snapshot(self) -> None:
        quote = quote_state_from_guard({"symbol": "PFE", "last": None}, now="ts", use_case="EXECUTION_GATE")

        self.assertTrue(quote.execution_blocked_due_to_stale_quote)
        self.assertFalse(quote.snapshot_request_used)
        self.assertFalse(quote.regulatory_snapshot_used)
        self.assertFalse(quote.paid_snapshot_risk)

    def test_delayed_and_frozen_data_cannot_pass_execution_readiness(self) -> None:
        delayed = quote_execution_readiness({"symbol": "PFE", "bid": 24, "bid_age_sec": 1, "market_data_type": 3}, side="SELL")
        frozen = quote_execution_readiness({"symbol": "PFE", "ask": 25, "ask_age_sec": 1, "market_data_type": 2}, side="BUY")

        self.assertFalse(delayed["ok"])
        self.assertIn("not live", delayed["blocked_reason"])
        self.assertFalse(frozen["ok"])
        self.assertIn("not live", frozen["blocked_reason"])

    def test_live_fresh_bid_and_ask_can_pass_quote_readiness(self) -> None:
        sell = quote_execution_readiness({"symbol": "PFE", "bid": 24, "bid_age_sec": 1, "market_data_type": 1}, side="SELL")
        buy = quote_execution_readiness({"symbol": "PFE", "ask": 25, "ask_age_sec": 1, "market_data_type": 1}, side="BUY")

        self.assertTrue(sell["ok"])
        self.assertTrue(buy["ok"])

    def test_reports_can_use_last_fallback_but_execution_cannot(self) -> None:
        report_quote = quote_state_from_guard({"symbol": "PFE", "last": 25, "last_age_sec": 10, "market_data_type": 1}, now="ts", use_case="DASHBOARD")
        execution_quote = quote_state_from_guard({"symbol": "PFE", "last": 25, "last_age_sec": 1, "market_data_type": 1}, now="ts", use_case="EXECUTION_GATE")

        self.assertFalse(report_quote.quote_stale)
        self.assertTrue(execution_quote.execution_blocked_due_to_stale_quote)

    def test_market_data_billing_safety_report_schema(self) -> None:
        report = build_report()

        self.assertIn("reqMktData_calls_audited", report)
        self.assertFalse(report["regulatory_snapshot_used"])

    def test_force_refresh_dry_run_submits_and_cancels_no_orders(self) -> None:
        with patch("trading.account_state_manager.force_refresh_state") as force, patch("trading.account_state_manager.build_account_state") as state:
            force.return_value = type(
                "Force",
                (),
                {
                    "force_refresh_performed": True,
                    "force_refresh_ok": False,
                    "positions_refreshed": True,
                    "open_orders_refreshed": True,
                    "quotes_refreshed": False,
                    "pnl_refreshed": False,
                    "protection_coverage_refreshed": True,
                    "blocked_reason": "quote missing",
                },
            )()
            state.return_value = type(
                "State",
                (),
                {
                    "state_stale": True,
                    "blocked_reason": "quote missing",
                    "timestamp": "ts",
                    "quotes": [],
                    "freshness": None,
                    "positions": [],
                    "open_orders": [],
                },
            )()
            payload = build_force_refresh_dry_run()

        self.assertEqual(payload["orders_submitted"], 0)
        self.assertEqual(payload["orders_cancelled"], 0)


if __name__ == "__main__":
    unittest.main()
