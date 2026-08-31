import unittest

from trading.event_router import build_event_router_report


class EventRouterTests(unittest.TestCase):
    def test_routes_report_only_actions_from_risk_reports(self) -> None:
        report = build_event_router_report(
            position_guard={"symbols": [{"symbol": "PFE", "position_qty": 8, "protective_stop_qty": 0}]},
            gap_risk={"symbols": [{"symbol": "PFE", "over_budget": True}]},
            gap_escape={"symbols": [{"symbol": "PFE", "emergency_action_allowed": True}]},
            event_risk={"symbols": [{"symbol": "PFE", "event_risk_score": 0.8}]},
            outside_rth={"symbols": [{"symbol": "PFE", "needs_STP_LMT_conversion": True}]},
            pool_membership={"records": [{"symbol": "PFE", "pool_name": "hot_pool", "included": True}]},
        )

        self.assertTrue(report["report_only"])
        actions = {row["recommended_action"] for row in report["events"]}
        self.assertIn("trigger_gap_risk_review", actions)
        self.assertIn("trigger_gap_escape_review", actions)
        self.assertIn("promote_to_hot_pool", actions)
        self.assertFalse(any(row.get("execution_allowed") for row in report["events"]))


if __name__ == "__main__":
    unittest.main()
