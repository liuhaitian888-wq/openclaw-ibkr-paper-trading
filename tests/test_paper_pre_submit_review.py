import unittest
from pathlib import Path

from research.paper_pre_submit_review import build_pre_submit_review


class PaperPreSubmitReviewTests(unittest.TestCase):
    def test_ready_review_requires_gate_order_snapshot_and_pnl(self) -> None:
        review = build_pre_submit_review(
            readiness_monitor={"status": "ready_for_validate_only_window"},
            execution_gate={
                "status": "ready_for_explicit_paper_submit",
                "selected_symbol": "AAPL",
                "selected_payload": {"symbol": "AAPL", "side": "BUY", "quantity": 1, "limit_price": 100.0},
            },
            tws_orders={"status": "ok", "open_order_count": 0, "execution_count": 0},
            pnl_snapshot={"account": "DU123", "net_liquidation": 100000.0, "open_positions": 0},
            artifact_paths={"gate": Path("gate.json")},
        )

        self.assertEqual(review.status, "ready_for_operator_confirmation")
        self.assertEqual(review.selected_symbol, "AAPL")

    def test_open_order_blocks_review(self) -> None:
        review = build_pre_submit_review(
            readiness_monitor={"status": "ready_for_validate_only_window"},
            execution_gate={
                "status": "ready_for_explicit_paper_submit",
                "selected_symbol": "AAPL",
                "selected_payload": {"symbol": "AAPL", "side": "BUY", "quantity": 1, "limit_price": 100.0},
            },
            tws_orders={"status": "ok", "open_order_count": 1, "execution_count": 0},
            pnl_snapshot={"account": "DU123"},
            artifact_paths={},
        )

        self.assertEqual(review.status, "blocked")


if __name__ == "__main__":
    unittest.main()
