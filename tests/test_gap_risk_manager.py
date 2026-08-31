import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch

from trading.gap_risk_manager import GapRiskConfig, build_gap_risk_report, gap_risk_row


class GapRiskManagerTests(unittest.TestCase):
    def test_worst_gap_loss_and_max_notional(self) -> None:
        row = gap_risk_row(
            symbol="AAPL",
            position_qty=100,
            market_price=100,
            avg_cost=90,
            account_net_liquidation=1_000_000,
            shock_pct=0.20,
            max_symbol_loss_pct=0.01,
        )
        self.assertEqual(row["estimated_gap_loss"], 2000)
        self.assertEqual(row["max_allowed_position_notional"], 50000)
        self.assertFalse(row["over_budget"])

    def test_over_budget_recommends_reduce_or_hedge(self) -> None:
        row = gap_risk_row(
            symbol="META",
            position_qty=1000,
            market_price=100,
            avg_cost=90,
            account_net_liquidation=1_000_000,
            shock_pct=0.30,
            max_symbol_loss_pct=0.01,
        )
        self.assertTrue(row["over_budget"])
        self.assertEqual(row["recommended_action"], "reduce_position_or_hedge")

    def test_event_risk_increases_gap_shock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch("trading.gap_risk_manager.REPORT_DIR", Path(tmp)):
            report = build_gap_risk_report(
                position_guard={"symbols": [{"symbol": "ABC", "position_qty": 100, "market_price": 100}]},
                account_net_liquidation=1_000_000,
                event_risk_report={"symbols": [{"symbol": "ABC", "event_adjusted_gap_shock": 0.45}]},
                config=GapRiskConfig(),
            )
        self.assertIn(0.45, {row["shock_pct"] for row in report["symbols"]})


if __name__ == "__main__":
    unittest.main()
