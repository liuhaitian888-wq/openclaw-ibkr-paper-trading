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

    def test_mode9_runtime_ensures_trade_lock_before_agent(self) -> None:
        text = Path("scripts/control_trading_mode.command").read_text(encoding="utf-8")

        self.assertIn("9) MODE9_RUNTIME - runtime state: ensure TRADE_LOCK API, then start autonomous agent", text)
        self.assertIn("1) DEV_LOCK      - developer state: code edits allowed, trading blocked", text)
        runtime_case = text[text.index("9|AUTONOMOUS_AGENT_BG") : text.index("10|MONITOR_ON")]
        self.assertIn("ensure_trade_lock_api_background", runtime_case)
        self.assertIn("start_autonomous_agent_background", runtime_case)
        self.assertLess(runtime_case.index("ensure_trade_lock_api_background"), runtime_case.index("start_autonomous_agent_background"))

    def test_interactive_menu_folds_advanced_controls(self) -> None:
        text = Path("scripts/control_trading_mode.command").read_text(encoding="utf-8")

        main_menu = text[text.index("show_main_menu()") : text.index("show_advanced_menu()")]
        advanced_menu = text[text.index("show_advanced_menu()") : text.index("if [[ ! -x")]
        interactive_block = text[text.index("show_main_menu") : text.index("case \"$choice\"")]
        self.assertIn("0) STOP", main_menu)
        self.assertIn("1) DEV_LOCK", main_menu)
        self.assertIn("2) MORE_TOOLS", main_menu)
        self.assertIn("9) MODE9_RUNTIME", main_menu)
        self.assertNotIn("3) HEALTH", main_menu)
        self.assertIn("3) HEALTH", advanced_menu)
        self.assertIn("22) IBKR_CALLBACK_DRY_RUN", advanced_menu)
        self.assertIn("Choose mode [0/1/2/9]", interactive_block)
        self.assertIn("Choose advanced mode", interactive_block)

    def test_mode9_runtime_keeps_hard_safety_flags(self) -> None:
        text = Path("scripts/control_trading_mode.command").read_text(encoding="utf-8")

        self.assertIn("set_mode9_runtime_env()", text)
        block = text[text.index("set_mode9_runtime_env()") : text.index("start_api_background()")]
        self.assertIn("set_trade_lock_env", block)
        self.assertIn("export LIVE_TRADING_ENABLED=false", block)
        self.assertIn("export ALLOW_MARKET_ORDERS=false", block)
        self.assertIn("export NO_PAID_MARKET_DATA_REQUESTS=true", block)
        self.assertIn("export ALLOW_REGULATORY_SNAPSHOT=false", block)
        self.assertIn("export ALLOW_SNAPSHOT_MARKET_DATA=false", block)
        self.assertIn("export ALLOW_DELAYED_DATA_FOR_EXECUTION=false", block)
        self.assertIn("export MARKET_DATA_EXECUTION_REQUIRES_LIVE=true", block)

    def test_mode9_runtime_reuses_existing_token_or_restarts_api(self) -> None:
        text = Path("scripts/control_trading_mode.command").read_text(encoding="utf-8")

        block = text[text.index("ensure_trade_lock_api_background()") : text.index("run_monitor_on()")]
        self.assertIn("load_trade_token_env >/dev/null 2>&1", block)
        self.assertIn('token_loaded=true', block)
        self.assertIn('[[ "$token_loaded" == "true" ]] && url="$(detect_trade_lock_api_url "$key")"', block)
        self.assertIn("no matching trade token was loaded; restarting for Mode 9 runtime", block)


if __name__ == "__main__":
    unittest.main()
