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

    def test_full_paper_automation_command_keeps_hard_safety_flags(self) -> None:
        text = Path("scripts/control_trading_mode.command").read_text(encoding="utf-8")

        self.assertIn("run_full_paper_automation()", text)
        self.assertIn("FULL_PAPER_AUTOMATION|full-paper-automation|full_paper_automation", text)
        block = text[text.index("run_full_paper_automation()") : text.index("if [[ ! -x")]
        self.assertIn("export TRADING_MODE=PAPER", block)
        self.assertIn("export LIVE_TRADING_ENABLED=false", block)
        self.assertIn("export ALLOW_MARKET_ORDERS=false", block)
        self.assertIn("export NO_PAID_MARKET_DATA_REQUESTS=true", block)
        self.assertIn("export ALLOW_REGULATORY_SNAPSHOT=false", block)
        self.assertIn("export ALLOW_SNAPSHOT_MARKET_DATA=false", block)
        self.assertIn("export MODE9_BUY_FREEZE=false", block)
        self.assertIn("export AUTO_BUY_ENABLED=true", block)
        self.assertIn("export LIVE_OPTIONS_EXECUTION=false", block)
        self.assertIn("export FULL_PAPER_AUTONOMOUS_RUN_ENABLED=true", block)
        self.assertIn("export FULL_PAPER_RUN_MINUTES=\"${FULL_PAPER_RUN_MINUTES:-5}\"", block)
        self.assertIn("export PAPER_BUY_MAX_NEW_POSITIONS_PER_DAY=\"${PAPER_BUY_MAX_NEW_POSITIONS_PER_DAY:-1}\"", block)
        self.assertIn("export PAPER_BUY_MAX_ORDER_NOTIONAL=\"${PAPER_BUY_MAX_ORDER_NOTIONAL:-25}\"", block)
        self.assertIn("export GAP_ESCAPE_PAPER_ONLY=true", block)


if __name__ == "__main__":
    unittest.main()
