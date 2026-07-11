import unittest
from pathlib import Path
from unittest.mock import patch

from trading.config import Settings
from trading.gap_escape_manager import GapEscapeConfig, gap_escape_row


class GapEscapeManagerTests(unittest.TestCase):
    def test_trigger_when_bid_below_stop_limit_and_marketable_lmt_price(self) -> None:
        with patch("trading.gap_escape_manager.read_lock", return_value={"process_name": "mode9_autonomous_agent"}):
            row = gap_escape_row(
                {
                    "symbol": "AAPL",
                    "position_qty": 10,
                    "bid": 94,
                    "ask": 94.5,
                    "last": 94.2,
                    "avg_cost": 100,
                    "quote_age_ms": 100,
                    "protective_stop_order_details": [{"aux_price": 95, "limit_price": 95}],
                },
                settings=_settings(),
                config=GapEscapeConfig(),
            )
        self.assertEqual(row["trigger_reason"], "bid <= active_stop_price")
        self.assertTrue(row["emergency_action_allowed"])
        self.assertEqual(row["sell_qty"], 5)
        self.assertEqual(row["normalized_emergency_limit_price"], 93.06)

    def test_blocked_when_quote_stale(self) -> None:
        with patch("trading.gap_escape_manager.read_lock", return_value={"process_name": "mode9_autonomous_agent"}):
            row = gap_escape_row(
                {"symbol": "AAPL", "position_qty": 10, "bid": 90, "ask": 91, "last": 90, "avg_cost": 100, "quote_age_ms": 10_000},
                settings=_settings(),
                config=GapEscapeConfig(),
            )
        self.assertIn("stale", row["blocked_reason"])
        self.assertFalse(row["emergency_action_allowed"])

    def test_blocked_when_spread_too_wide(self) -> None:
        with patch("trading.gap_escape_manager.read_lock", return_value={"process_name": "mode9_autonomous_agent"}):
            row = gap_escape_row(
                {"symbol": "AAPL", "position_qty": 10, "bid": 90, "ask": 95, "last": 90, "avg_cost": 100, "quote_age_ms": 100},
                settings=_settings(),
                config=GapEscapeConfig(max_spread_pct=0.02),
            )
        self.assertIn("spread", row["blocked_reason"])
        self.assertFalse(row["emergency_action_allowed"])


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
