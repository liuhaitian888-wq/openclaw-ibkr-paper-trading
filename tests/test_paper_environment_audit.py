import tempfile
import unittest
from pathlib import Path

from trading.config import Settings
from trading.paper_environment_audit import build_environment_audit


def make_settings(directory: str, **overrides: object) -> Settings:
    values = {
        "api_key": "x" * 32,
        "api_host": "127.0.0.1",
        "api_port": 8787,
        "trading_mode": "DRY_RUN",
        "allow_tws_staging": False,
        "allow_paper_transmit": False,
        "allow_outside_rth": False,
        "trading_kill_switch": False,
        "trade_session_token": "",
        "tws_host": "127.0.0.1",
        "tws_port": 7497,
        "tws_client_id": 22,
        "tws_status_timeout": 0.01,
        "allowed_symbols": frozenset({"AAPL", "MSFT", "SPY"}),
        "max_quantity": 1,
        "max_order_value": 200.0,
        "max_risk_per_order": 10.0,
        "max_daily_notional_value": None,
        "daily_notional_timezone": "Europe/Berlin",
        "streaming_market_data_enabled": False,
        "streaming_symbols": ("AAPL", "MSFT", "NVDA"),
        "streaming_max_symbols": 3,
        "streaming_stale_ms": 3000.0,
        "streaming_tws_host": "127.0.0.1",
        "streaming_tws_port": 7497,
        "streaming_client_id": 32,
        "audit_db": Path(directory) / "audit.sqlite3",
    }
    values.update(overrides)
    return Settings(**values)


READY_HEALTH = {
    "lock_state": "TRADE_LOCK",
    "paper_transmit_enabled": True,
    "kill_switch_enabled": False,
    "tws": {
        "ready_for_orders": True,
        "paper_account": "DU12345",
        "error": "",
    },
}


class PaperEnvironmentAuditTests(unittest.TestCase):
    def test_ready_report_requires_trade_lock_and_tws_paper_account(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(
                directory,
                trading_mode="PAPER",
                allow_paper_transmit=True,
                trade_session_token="session-ok",
            )

            report = build_environment_audit(settings, health=READY_HEALTH)

            self.assertEqual(report.status, "ready_for_one_share_paper_trial")
            self.assertTrue(all(item.status == "pass" for item in report.items if item.required))

    def test_dry_run_without_health_is_blocked_with_next_steps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = build_environment_audit(
                make_settings(directory),
                health=None,
                api_error="connection refused",
            )

            self.assertEqual(report.status, "blocked")
            item_statuses = {item.name: item.status for item in report.items}
            self.assertEqual(item_statuses["paper_mode"], "fail")
            self.assertEqual(item_statuses["api_health_reachable"], "fail")
            self.assertIn("Start the Trading API in TRADE_LOCK", " ".join(report.next_steps))

    def test_unready_tws_blocks_even_when_local_settings_are_paper(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(
                directory,
                trading_mode="PAPER",
                allow_paper_transmit=True,
                trade_session_token="session-ok",
            )
            health = dict(READY_HEALTH)
            health["tws"] = {
                "ready_for_orders": False,
                "paper_account": None,
                "error": "TWS API is not reachable",
            }

            report = build_environment_audit(settings, health=health)

            self.assertEqual(report.status, "blocked")
            item_statuses = {item.name: item.status for item in report.items}
            self.assertEqual(item_statuses["health_tws_ready"], "fail")
            self.assertEqual(item_statuses["health_du_paper_account"], "fail")


if __name__ == "__main__":
    unittest.main()
