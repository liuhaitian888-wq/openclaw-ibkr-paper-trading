import unittest
from unittest.mock import patch

from scripts.run_mode9_report_only_infrastructure_cycle import run_report_only_cycle


class Mode9ReportOnlyInfrastructureCycleTests(unittest.TestCase):
    def test_cycle_is_report_only_and_calls_core_modules(self) -> None:
        with patch("scripts.run_mode9_report_only_infrastructure_cycle.Settings.load", return_value=object()), \
            patch("scripts.run_mode9_report_only_infrastructure_cycle.build_position_guard_report", return_value={"symbols": []}), \
            patch("scripts.run_mode9_report_only_infrastructure_cycle.build_pool_manager_report", return_value={"membership": {"records": []}}), \
            patch("scripts.run_mode9_report_only_infrastructure_cycle.build_event_risk_report", return_value={"symbols": []}), \
            patch("scripts.run_mode9_report_only_infrastructure_cycle.build_gap_risk_report", return_value={"symbols": []}), \
            patch("scripts.run_mode9_report_only_infrastructure_cycle.run_position_protection", return_value={"records": []}), \
            patch("scripts.run_mode9_report_only_infrastructure_cycle.build_gap_escape_report", return_value={"symbols": []}), \
            patch("scripts.run_mode9_report_only_infrastructure_cycle.build_event_router_report", return_value={"events": []}), \
            patch("scripts.run_mode9_report_only_infrastructure_cycle.build_profit_lock_report", return_value={"symbols": []}), \
            patch("scripts.run_mode9_report_only_infrastructure_cycle.build_take_profit_report", return_value={"symbols": []}), \
            patch("scripts.run_mode9_report_only_infrastructure_cycle.build_trailing_profit_report", return_value={"symbols": []}), \
            patch("scripts.run_mode9_report_only_infrastructure_cycle.build_options_hedge_report", return_value={"symbols": []}), \
            patch("scripts.run_mode9_report_only_infrastructure_cycle.build_all_reports", return_value=None):
            payload = run_report_only_cycle()

        self.assertEqual(payload["orders_submitted"], 0)
        self.assertTrue(payload["report_only"])
        self.assertFalse(payload["buy_submitted"])
        self.assertIn("pool_manager", payload["reports"])
        self.assertIn("event_router", payload["reports"])
        self.assertIn("profit_lock", payload["reports"])


if __name__ == "__main__":
    unittest.main()
