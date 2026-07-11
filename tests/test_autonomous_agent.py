from datetime import datetime, timezone
import unittest

from scripts.run_autonomous_trading_agent import (
    build_research_tasks,
    mode9_buy_freeze,
    streaming_report_payload,
    update_market_state,
)
from trading.market_data import Quote


class AutonomousAgentTests(unittest.TestCase):
    def test_update_market_state_ranks_intracycle_movers(self) -> None:
        state = {
            "AAPL": {"last": 100.0, "timestamp": 1.0},
            "MSFT": {"last": 200.0, "timestamp": 1.0},
        }
        now = datetime.now(timezone.utc)

        movers = update_market_state(
            state,
            [
                Quote("AAPL", 101.0, now, "test", bid=100.99, ask=101.01),
                Quote("MSFT", 196.0, now, "test", bid=195.9, ask=196.1),
            ],
        )

        self.assertEqual(movers[0]["symbol"], "MSFT")
        self.assertEqual(state["AAPL"]["last"], 101.0)

    def test_build_research_tasks_marks_allowed_symbols_high_priority(self) -> None:
        tasks = build_research_tasks(
            [
                {"symbol": "AAPL", "step_return": 0.01},
                {"symbol": "XYZ", "step_return": 0.02},
            ],
            module_allowed=["AAPL"],
        )

        self.assertEqual(tasks[0]["priority"], "high")
        self.assertEqual(tasks[1]["priority"], "watch")
        self.assertIn("SEC filings and earnings calendar", tasks[0]["requested_checks"])

    def test_streaming_report_is_empty_when_disabled(self) -> None:
        payload = streaming_report_payload(None)

        self.assertEqual(payload["streaming_symbols"], [])
        self.assertEqual(payload["streaming_quote_count"], 0)
        self.assertEqual(payload["streaming_stale_symbols"], [])
        self.assertEqual(payload["streaming_errors"], [])
        self.assertEqual(payload["streaming_quotes"], {})

    def test_mode9_buy_freeze_defaults_on(self) -> None:
        import os
        from unittest.mock import patch

        env = {key: value for key, value in os.environ.items() if key != "MODE9_BUY_FREEZE"}
        with patch.dict(os.environ, env, clear=True):
            self.assertTrue(mode9_buy_freeze())


if __name__ == "__main__":
    unittest.main()
