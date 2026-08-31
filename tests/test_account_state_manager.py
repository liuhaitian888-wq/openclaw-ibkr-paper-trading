import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from trading.account_state_manager import (
    account_dashboard_payload,
    build_account_state,
    force_refresh_state,
    quote_execution_readiness,
    quote_state_from_guard,
    require_fresh_state_for_execution,
    stale_status,
)
from trading.ibkr_streaming import StreamingQuoteState, streaming_blocked_reason
from trading.module_interfaces import (
    AccountState,
    ForceRefreshResult,
    OpenOrderState,
    PnLState,
    PositionState,
    QuoteState,
    StateFreshness,
)


class AccountStateManagerTests(unittest.TestCase):
    def test_state_schema_dataclasses_have_required_fields(self) -> None:
        freshness = StateFreshness(1, 2, 3, 4, 5, 6)
        position = PositionState("ts", "PFE", 8, 24.0, 25.0, 24.9, 25.1, 25.0, 200, 8, 0.04, False, 0.008, 5, 2)
        quote = QuoteState(
            "ts",
            "PFE",
            24.9,
            25.1,
            25.0,
            1,
            1,
            1,
            0.008,
            True,
            "test",
            "regular",
            "EXECUTION_GATE",
            1,
            "live",
            True,
            False,
            False,
            False,
            False,
            False,
            True,
            "",
            5,
            1,
            "",
            False,
            False,
        )
        order = OpenOrderState("ts", "PFE", "SELL", "STP", 8, 8, None, 23.0, True, False, "PreSubmitted", 1, 3)
        pnl = PnLState("ts", "acct", None, 1, 2, 3, 4, True, True, False, True, False, True, "fallback")
        force = ForceRefreshResult(True, True, False, True, True, False, False, True, "stale")
        state = AccountState("ts", "PAPER", "acct", 1, 2, 3, 4, 5, 6, positions=[position], quotes=[quote], open_orders=[order], pnl=[pnl], protection_coverage=[], freshness=freshness, state_stale=True, blocked_reason="blocked", used_cached_state=True, force_refresh=force)

        self.assertEqual(state.positions[0].symbol, "PFE")
        self.assertEqual(state.quotes[0].bid_age_sec, 1)
        self.assertEqual(state.open_orders[0].order_type, "STP")
        self.assertTrue(state.force_refresh.force_refresh_required)

    def test_stale_state_detection(self) -> None:
        stale, reason = stale_status(StateFreshness(1, 999, 1, 1, 1, 1))

        self.assertTrue(stale)
        self.assertIn("positions stale", reason)

    def test_account_state_report_generation_from_cached_inputs(self) -> None:
        guard = {
            "timestamp": "2026-07-10T00:00:00+00:00",
            "account": "DU123",
            "symbols": [
                {
                    "symbol": "PFE",
                    "position_qty": 8,
                    "avg_cost": 24,
                    "market_price": 25,
                    "bid": 24.9,
                    "ask": 25.1,
                    "last": 25,
                    "quote_age_ms": 1000,
                    "market_value": 200,
                    "unrealized_pnl": 8,
                    "protective_stop_qty": 8,
                    "position_covered_by_stop": True,
                }
            ],
        }
        account = {"account": "DU123", "net_liquidation": 1000, "cash": 500, "buying_power": 2000, "realized_pnl": 1, "unrealized_pnl": 8}

        state = build_account_state(position_guard_report=guard, account_snapshot=account, write_reports_enabled=False)

        self.assertEqual(state.account_id, "DU123")
        self.assertEqual(state.positions[0].symbol, "PFE")
        self.assertEqual(len(state.quotes), 5)
        self.assertEqual(state.quotes[0].bid_age_sec, 1)
        self.assertEqual(state.metadata["orders_submitted"], 0)

    def test_streaming_quote_cache_feeds_account_state_manager(self) -> None:
        guard = {
            "account": "DU123",
            "symbols": [
                {
                    "symbol": "PFE",
                    "position_qty": 8,
                    "avg_cost": 24,
                    "market_value": 200,
                    "unrealized_pnl": 8,
                    "protective_stop_qty": 8,
                    "position_covered_by_stop": True,
                }
            ],
        }
        diagnostics = {
            "rows": [
                {
                    "symbol": "PFE",
                    "bid": 24.9,
                    "ask": 25.1,
                    "last": 25.0,
                    "bid_age_sec": 1,
                    "ask_age_sec": 1,
                    "last_age_sec": 1,
                    "market_data_type": 1,
                    "market_data_type_name": "live",
                    "blocked_reason": "",
                }
            ]
        }

        state = build_account_state(position_guard_report=guard, account_snapshot={"account": "DU123"}, streaming_diagnostics=diagnostics, write_reports_enabled=False)

        execution_quotes = [quote for quote in state.quotes if quote.symbol == "PFE" and quote.quote_use_case == "EXECUTION_GATE"]
        self.assertEqual(state.positions[0].bid, 24.9)
        self.assertTrue(execution_quotes[0].live_data_confirmed)
        self.assertTrue(execution_quotes[0].execution_allowed_from_quote)

    def test_quote_state_splits_bid_ask_last_and_use_case_threshold(self) -> None:
        row = {"symbol": "PFE", "bid": 24.9, "ask": 25.1, "last": 25.0, "bid_age_sec": 1, "ask_age_sec": 2, "last_age_sec": 30, "market_data_type": 1}

        quote = quote_state_from_guard(row, now="ts", use_case="EXECUTION_GATE")

        self.assertEqual(quote.bid, 24.9)
        self.assertEqual(quote.ask, 25.1)
        self.assertEqual(quote.last, 25.0)
        self.assertEqual(quote.bid_age_sec, 1)
        self.assertEqual(quote.ask_age_sec, 2)
        self.assertEqual(quote.last_age_sec, 30)
        self.assertEqual(quote.threshold_used_sec, 5.0)
        self.assertFalse(quote.execution_blocked_due_to_stale_quote)

    def test_sell_execution_requires_fresh_bid_and_buy_requires_fresh_ask(self) -> None:
        sell = quote_execution_readiness({"symbol": "PFE", "ask": 25.1, "ask_age_sec": 1, "last": 25, "market_data_type": 1}, side="SELL")
        buy = quote_execution_readiness({"symbol": "PFE", "bid": 24.9, "bid_age_sec": 1, "last": 25, "market_data_type": 1}, side="BUY")

        self.assertFalse(sell["ok"])
        self.assertIn("bid is missing", sell["blocked_reason"])
        self.assertFalse(buy["ok"])
        self.assertIn("ask is missing", buy["blocked_reason"])

    def test_reports_may_use_last_but_execution_blocks_without_bid(self) -> None:
        dashboard = quote_state_from_guard({"symbol": "PFE", "last": 25, "last_age_sec": 10}, now="ts", use_case="DASHBOARD")
        execution = quote_state_from_guard({"symbol": "PFE", "last": 25, "last_age_sec": 1}, now="ts", use_case="EXECUTION_GATE")

        self.assertFalse(dashboard.quote_stale)
        self.assertTrue(execution.execution_blocked_due_to_stale_quote)
        self.assertIn("bid is missing", execution.stale_reason)

    def test_streaming_bid_ask_gap_uses_market_session_classifier(self) -> None:
        state = StreamingQuoteState(symbol="PFE", last=23.5)

        with patch("trading.ibkr_streaming.classify_streaming_bid_ask_gap", return_value="market_closed_no_active_bid_ask"):
            reason = streaming_blocked_reason(state, started=True)

        self.assertEqual(reason, "market_closed_no_active_bid_ask")

    def test_execution_requires_force_refresh_and_blocks_failure(self) -> None:
        with patch("trading.account_state_manager.build_position_guard_report", side_effect=RuntimeError("down")):
            result = force_refresh_state(perform=True)

        self.assertTrue(result.force_refresh_required)
        self.assertTrue(result.force_refresh_performed)
        self.assertFalse(result.force_refresh_ok)
        self.assertIn("force refresh failed", result.blocked_reason)

    def test_require_fresh_state_for_execution_blocks_stale_state(self) -> None:
        with patch("trading.account_state_manager.build_account_state") as mocked:
            mocked.return_value = AccountState(
                "ts",
                "PAPER",
                "acct",
                None,
                None,
                None,
                None,
                None,
                None,
                freshness=StateFreshness(None, None, None, None, None, None),
                state_stale=True,
                blocked_reason="positions missing",
                force_refresh=ForceRefreshResult(True, True, True, True, True, True, True, True, ""),
            )
            result = require_fresh_state_for_execution()

        self.assertFalse(result.force_refresh_ok)
        self.assertEqual(result.blocked_reason, "positions missing")

    def test_account_dashboard_generation(self) -> None:
        state = AccountState(
            "ts",
            "PAPER",
            "acct",
            1000,
            500,
            2000,
            300,
            1,
            2,
            positions=[PositionState("ts", "PFE", 8, 24, 25, 24.9, 25.1, 25, 200, 8, 0.04, False, 0.008, 1, 1)],
            open_orders=[],
            freshness=StateFreshness(1, 1, 1, 1, 1, 1),
            state_stale=False,
        )

        dashboard = account_dashboard_payload(state)

        self.assertEqual(dashboard["number_of_positions"], 1)
        self.assertFalse(dashboard["live_trading_enabled"])
        self.assertTrue(dashboard["paper_only"])

    def test_report_files_are_written(self) -> None:
        state = build_account_state(
            position_guard_report={"account": "DU123", "symbols": []},
            account_snapshot={"account": "DU123"},
            write_reports_enabled=True,
        )

        self.assertEqual(state.metadata["orders_submitted"], 0)
        self.assertTrue(Path("reports/account_state/latest.json").exists())
        self.assertTrue(Path("reports/quote_state/latest.json").exists())
        self.assertTrue(Path("reports/account_dashboard/latest.json").exists())
        payload = json.loads(Path("reports/account_state/latest.json").read_text())
        self.assertEqual(payload["orders_submitted"], 0)
        quote_payload = json.loads(Path("reports/quote_state/latest.json").read_text())
        self.assertIn("thresholds_sec", quote_payload)


if __name__ == "__main__":
    unittest.main()
