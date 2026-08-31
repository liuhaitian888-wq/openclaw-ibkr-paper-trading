import unittest
from pathlib import Path

from scripts.build_strategy_extension_status import build_status, write_reports
from trading.config import Settings


class StrategyExtensionStatusTests(unittest.TestCase):
    def test_status_is_report_only_and_does_not_enable_live_or_buy(self) -> None:
        payload = build_status(
            _settings(),
            agent_latest={
                "streaming_enabled": False,
                "streaming_symbols": [],
                "streaming_quote_count": 0,
            },
        )
        self.assertTrue(payload["paper_only"])
        self.assertFalse(payload["live_enabled"])
        for module in payload["modules"].values():
            self.assertTrue(module["report_only"])
            self.assertIn(module["trade_effect"], {"none", "protective_sell_stp_only"})
        self.assertEqual(payload["modules"]["full_universe_streaming"]["strategy_input_enabled"], False)

    def test_write_reports_creates_json_and_markdown(self) -> None:
        import tempfile
        from unittest.mock import patch

        payload = build_status(_settings(), agent_latest={})
        with tempfile.TemporaryDirectory() as tmp, patch("scripts.build_strategy_extension_status.REPORT_DIR", Path(tmp)):
            write_reports(payload)
            self.assertTrue((Path(tmp) / "status_latest.json").exists())
            self.assertTrue((Path(tmp) / "status_latest.md").exists())


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
        streaming_symbols=("AAPL", "MSFT", "NVDA"),
        streaming_max_symbols=3,
        streaming_stale_ms=3000,
        streaming_tws_host="127.0.0.1",
        streaming_tws_port=7497,
        streaming_client_id=32,
        audit_db=Path(":memory:"),
    )


if __name__ == "__main__":
    unittest.main()
