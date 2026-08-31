import unittest
from pathlib import Path

from trading.config import Settings
from trading.options_hedge_planner import OptionHedgeConfig, option_hedge_plan


class OptionsHedgePlannerTests(unittest.TestCase):
    def test_not_triggered_below_notional_threshold(self) -> None:
        row = option_hedge_plan(
            {"symbol": "AAPL", "position_qty": 100, "market_price": 100},
            event={},
            config=OptionHedgeConfig(),
            settings=_settings(),
        )
        self.assertFalse(row["eligible_for_options_hedge"])
        self.assertEqual(row["action_taken"], "report_only")

    def test_triggered_above_notional_threshold(self) -> None:
        row = option_hedge_plan(
            {"symbol": "META", "position_qty": 100, "market_price": 700},
            event={"event_risk_score": 0.8},
            config=OptionHedgeConfig(),
            settings=_settings(),
        )
        self.assertTrue(row["eligible_for_options_hedge"])
        self.assertEqual(row["strategy"], "collar")
        self.assertTrue(row["covered_call_safe"])
        self.assertFalse(row["naked_option_risk"])
        self.assertFalse(row["action_allowed"])

    def test_quantity_under_100_blocks_single_stock_option_hedge(self) -> None:
        row = option_hedge_plan(
            {"symbol": "MSFT", "position_qty": 50, "market_price": 1000},
            event={},
            config=OptionHedgeConfig(),
            settings=_settings(),
        )
        self.assertFalse(row["eligible_for_options_hedge"])
        self.assertEqual(row["reason"], "single_stock_option_hedge_not_available_due_to_small_share_count")


def _settings() -> Settings:
    return Settings(
        api_key="key",
        api_host="127.0.0.1",
        api_port=8787,
        trading_mode="PAPER",
        allow_tws_staging=True,
        allow_paper_transmit=True,
        allow_outside_rth=True,
        trading_kill_switch=False,
        trade_session_token="token",
        tws_host="127.0.0.1",
        tws_port=7497,
        tws_client_id=22,
        tws_status_timeout=1,
        allowed_symbols=frozenset({"AAPL"}),
        max_quantity=1,
        max_order_value=400,
        max_risk_per_order=10,
        max_daily_notional_value=None,
        daily_notional_timezone="Europe/Berlin",
        streaming_market_data_enabled=False,
        streaming_symbols=(),
        streaming_max_symbols=3,
        streaming_stale_ms=3000,
        streaming_tws_host="127.0.0.1",
        streaming_tws_port=7497,
        streaming_client_id=32,
        audit_db=Path(":memory:"),
    )


if __name__ == "__main__":
    unittest.main()
