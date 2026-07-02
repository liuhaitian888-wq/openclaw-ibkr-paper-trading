import unittest

from trading.dashboard import render_dashboard_html
from trading.simulation import StrategySimulationConfig, run_strategy_simulation


class DashboardTests(unittest.TestCase):
    def test_dashboard_contains_core_sections(self) -> None:
        data = run_strategy_simulation(
            StrategySimulationConfig(
                symbols=["AAPL", "MSFT"],
                steps=4,
                source="simulated",
            )
        )

        html = render_dashboard_html(data)

        self.assertIn("OpenClaw Strategy Dashboard", html)
        self.assertIn("Value Pool", html)
        self.assertIn("Quote Cache", html)
        self.assertIn("Paper Proposals", html)
        self.assertIn("Signal Timeline", html)

    def test_dashboard_can_auto_refresh_and_show_missing_symbols(self) -> None:
        html = render_dashboard_html(
            {
                "source": "ibkr-readonly",
                "symbols": ["AAPL", "MSFT"],
                "returned_symbols": ["AAPL"],
                "missing_symbols": ["MSFT"],
                "feed_errors": [],
                "value_pool": [],
                "events": [],
                "cache": [],
            },
            auto_refresh_seconds=5,
        )

        self.assertIn('http-equiv="refresh"', html)
        self.assertIn("Auto refresh every 5s", html)
        self.assertIn("missing_symbols", html)


if __name__ == "__main__":
    unittest.main()
