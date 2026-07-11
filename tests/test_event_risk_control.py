import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch

from trading.event_risk_control import EventRiskConfig, build_event_risk_report


class EventRiskControlTests(unittest.TestCase):
    def test_high_event_blocks_buy_and_requires_outside_rth_protection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch("trading.event_risk_control.REPORT_DIR", Path(tmp)):
            report = build_event_risk_report(
                position_guard={"symbols": [{"symbol": "META", "position_qty": 100, "market_price": 700}]},
                account_net_liquidation=1_000_000,
                config=EventRiskConfig(),
                local_events={"META": {"event_risk_score": 0.9, "event_type": "earnings", "base_gap_shock": 0.20}},
            )
        row = report["symbols"][0]
        self.assertTrue(row["block_new_buy"])
        self.assertTrue(row["require_outside_rth_protection"])
        self.assertTrue(row["require_option_hedge"])
        self.assertEqual(row["event_adjusted_gap_shock"], 0.3)


if __name__ == "__main__":
    unittest.main()
