from datetime import datetime, timezone
import unittest

from scripts.run_autonomous_trading_agent import (
    build_research_tasks,
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


if __name__ == "__main__":
    unittest.main()
