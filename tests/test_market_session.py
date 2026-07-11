import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from trading.market_session import (
    MarketSessionConfig,
    MarketSessionState,
    current_market_session,
    market_session_md,
    parse_ibkr_trading_hours,
)
from scripts.run_full_paper_rollout import market_session_blocks_quote_wait


ET = ZoneInfo("America/New_York")


class MarketSessionTests(unittest.TestCase):
    def test_regular_session_expects_live_bid_ask(self) -> None:
        report = current_market_session(now=datetime(2026, 7, 10, 10, 0, tzinfo=ET))

        self.assertEqual(report.session_state, MarketSessionState.REGULAR.value)
        self.assertTrue(report.expected_live_bid_ask)
        self.assertTrue(report.allows_quote_wait)

    def test_premarket_session_expects_live_bid_ask(self) -> None:
        report = current_market_session(now=datetime(2026, 7, 10, 8, 0, tzinfo=ET))

        self.assertEqual(report.session_state, MarketSessionState.PREMARKET.value)
        self.assertTrue(report.expected_live_bid_ask)

    def test_afterhours_session_expects_live_bid_ask(self) -> None:
        report = current_market_session(now=datetime(2026, 7, 10, 17, 0, tzinfo=ET))

        self.assertEqual(report.session_state, MarketSessionState.AFTERHOURS.value)
        self.assertTrue(report.expected_live_bid_ask)

    def test_after_afterhours_close_blocks_quote_wait(self) -> None:
        report = current_market_session(now=datetime(2026, 7, 10, 20, 6, tzinfo=ET))

        self.assertEqual(report.session_state, MarketSessionState.CLOSED.value)
        self.assertFalse(report.expected_live_bid_ask)
        self.assertFalse(report.allows_quote_wait)
        self.assertEqual(report.blocked_reason, "market_closed_no_live_bid_ask_expected")
        self.assertTrue(market_session_blocks_quote_wait(report.to_dict()))

    def test_weekend_blocks_quote_wait(self) -> None:
        report = current_market_session(now=datetime(2026, 7, 11, 12, 0, tzinfo=ET))

        self.assertEqual(report.session_state, MarketSessionState.WEEKEND.value)
        self.assertFalse(report.expected_live_bid_ask)
        self.assertIn("weekend", report.blocked_reason)

    def test_holiday_blocks_quote_wait(self) -> None:
        report = current_market_session(now=datetime(2026, 7, 3, 10, 0, tzinfo=ET))

        self.assertEqual(report.session_state, MarketSessionState.HOLIDAY.value)
        self.assertFalse(report.allows_execution_readiness_check)

    def test_early_close_active_then_closed_after_1300(self) -> None:
        active = current_market_session(now=datetime(2026, 11, 27, 12, 0, tzinfo=ET))
        closed = current_market_session(now=datetime(2026, 11, 27, 13, 5, tzinfo=ET))

        self.assertEqual(active.session_state, MarketSessionState.EARLY_CLOSE.value)
        self.assertTrue(active.expected_live_bid_ask)
        self.assertEqual(closed.session_state, MarketSessionState.CLOSED.value)
        self.assertFalse(closed.expected_live_bid_ask)

    def test_symbol_rows_report_contract_details_when_provided(self) -> None:
        report = current_market_session(
            now=datetime(2026, 7, 10, 10, 0, tzinfo=ET),
            symbols=["PFE"],
            contract_details={"PFE": {"timeZoneId": "US/Eastern", "tradingHours": "20260710:0400-2000"}},
        )

        self.assertTrue(report.contract_details_available)
        self.assertEqual(report.symbols[0]["symbol"], "PFE")
        self.assertTrue(report.symbols[0]["contract_details_available"])
        self.assertTrue(report.symbols[0]["ibkr_trading_hours_available"])
        self.assertEqual(report.symbols[0]["parsed_trading_hours"][0]["start"], "0400")

    def test_contract_details_closed_overrides_calendar_open_for_symbol(self) -> None:
        report = current_market_session(
            now=datetime(2026, 7, 10, 10, 0, tzinfo=ET),
            symbols=["PFE"],
            contract_details={"PFE": {"timeZoneId": "US/Eastern", "tradingHours": "20260710:CLOSED", "liquidHours": "20260710:CLOSED"}},
        )

        self.assertEqual(report.session_state, MarketSessionState.REGULAR.value)
        self.assertEqual(report.symbols[0]["contract_session_state"], "CLOSED")
        self.assertTrue(report.symbols[0]["calendar_contract_conflict"])
        self.assertEqual(report.symbols[0]["contract_blocked_reason"], "calendar_contract_session_conflict")

    def test_unknown_calendar_blocks_execution_when_verified_calendar_required(self) -> None:
        config = MarketSessionConfig(require_verified_calendar=True)

        with patch("trading.market_session._calendar_status_from_package", return_value=None), patch(
            "trading.market_session._calendar_status_from_local_file",
            return_value=None,
        ):
            report = current_market_session(now=datetime(2026, 7, 10, 10, 0, tzinfo=ET), config=config)

        self.assertEqual(report.session_state, MarketSessionState.UNKNOWN.value)
        self.assertFalse(report.allows_quote_wait)
        self.assertEqual(report.blocked_reason, "market_session_unknown")

    def test_market_session_markdown_contains_contract_fields(self) -> None:
        report = current_market_session(
            now=datetime(2026, 7, 10, 10, 0, tzinfo=ET),
            symbols=["PFE"],
            contract_details={"PFE": {"timeZoneId": "US/Eastern", "tradingHours": "20260710:CLOSED"}},
        )
        text = market_session_md(report.to_dict())

        self.assertIn("IBKR Hours", text)
        self.assertIn("Contract State", text)

    def test_parse_ibkr_trading_hours_handles_closed(self) -> None:
        rows = parse_ibkr_trading_hours("20260710:0400-2000;20260711:CLOSED")

        self.assertEqual(rows[0]["start"], "0400")
        self.assertTrue(rows[1]["closed"])


if __name__ == "__main__":
    unittest.main()
