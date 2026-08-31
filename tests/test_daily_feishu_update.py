import unittest

from scripts.generate_daily_feishu_update import explain_zero_submissions, status_lines


class DailyFeishuUpdateTests(unittest.TestCase):
    def test_status_lines_include_repair_mode_and_blocked_reason(self) -> None:
        text = status_lines(
            {
                "mode9_running": True,
                "mode9_pid": 123,
                "agent_latest_created_at": "2026-07-10T00:00:00+00:00",
                "agent_latest_age_seconds": 10.0,
                "cycles_last_update_age_seconds": 9.0,
                "trading_api_health_ok": True,
                "trading_api_health_error": "",
                "buy_freeze": True,
                "position_repair_enabled": True,
                "position_repair_mode": "run",
                "paper_operation_mode": "paper_protection_run",
                "test_repair_success": False,
                "run_allowed": False,
                "run_blocked_reason": "latest test repair success is not true",
                "last_strategy_run_at": "reports/pool_strategy_module.json",
                "strategy_submitted_count": 0,
                "position_protection_submitted_count": 0,
                "top_skip_reasons": [("spread is too wide", 3)],
                "pnl_sample_age_seconds": 999.0,
                "zero_submission_reason": "position repair run blocked",
            }
        )
        self.assertIn("position_repair_mode: run", text)
        self.assertIn("paper_operation_mode: paper_protection_run", text)
        self.assertIn("run_blocked_reason: latest test repair success is not true", text)

    def test_zero_submission_explanation_names_repair_state(self) -> None:
        text = explain_zero_submissions(
            buy_freeze=True,
            repair_enabled=True,
            repair_mode="run",
            run_blocked_reason="latest test repair success is not true",
            strategy_submitted_count=0,
            position_submitted_count=0,
            skip_reasons=[("spread is too wide", 5)],
            api_ok=True,
        )
        self.assertIn("BUY freeze enabled", text)
        self.assertIn("position repair run blocked", text)
        self.assertIn("spread is too wide=5", text)


if __name__ == "__main__":
    unittest.main()
