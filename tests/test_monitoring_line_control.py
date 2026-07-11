import unittest
from pathlib import Path


class MonitoringLineControlTests(unittest.TestCase):
    def test_monitor_on_keeps_safety_flags_conservative(self) -> None:
        text = Path("scripts/control_trading_mode.command").read_text(encoding="utf-8")

        monitor_on = text[text.index("run_monitor_on()") : text.index("run_monitor_off()")]
        self.assertIn("export MODE9_BUY_FREEZE=true", monitor_on)
        self.assertIn("export LIVE_TRADING_ENABLED=false", monitor_on)
        self.assertIn("export SIX_LAYER_POOLS_EXECUTION_ACTIVE=false", monitor_on)
        self.assertIn("export TRADE_POOL_BUY_EXECUTION_ENABLED=false", monitor_on)
        self.assertIn("export ALLOW_OPTIONS_EXECUTION=false", monitor_on)
        self.assertIn("export ALLOW_MARKET_ORDERS=false", monitor_on)

    def test_market_session_and_rollout_precheck_commands_exist(self) -> None:
        text = Path("scripts/control_trading_mode.command").read_text(encoding="utf-8")

        self.assertIn("run_market_session()", text)
        self.assertIn("run_rollout_precheck()", text)
        self.assertIn("MARKET_SESSION|market-session|market_session", text)
        self.assertIn("ROLLOUT_PRECHECK|rollout-precheck|rollout_precheck", text)
        safe_env = text[text.index("set_safe_report_env()") : text.index("run_market_session()")]
        self.assertIn("export MODE9_BUY_FREEZE=true", safe_env)
        self.assertIn("export LIVE_TRADING_ENABLED=false", safe_env)
        self.assertIn("export ALLOW_REGULATORY_SNAPSHOT=false", safe_env)
        self.assertIn("export ALLOW_SNAPSHOT_MARKET_DATA=false", safe_env)
        self.assertIn("export POSITION_PROTECTION_REPAIR_ENABLED=false", safe_env)


if __name__ == "__main__":
    unittest.main()
