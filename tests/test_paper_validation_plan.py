import json
import tempfile
import unittest
from pathlib import Path

from research.paper_validation_plan import build_plan, load_diagnostics, write_plan


class PaperValidationPlanTests(unittest.TestCase):
    def test_negative_z_candidate_creates_buy_validate_payload(self) -> None:
        plan = build_plan(
            [
                {
                    "symbol": "AAPL",
                    "last_price": 100.25,
                    "diagnostics": {
                        "verdict": "research_candidate",
                        "mean_reversion_score": 75.0,
                        "latest_z_score": -1.4,
                    },
                }
            ],
            diagnostics_path=Path("diagnostics.json"),
            entry_z=1.0,
        )

        self.assertEqual(plan.validate_payload_count, 1)
        candidate = plan.candidates[0]
        self.assertEqual(candidate.action, "VALIDATE_BUY_LIMIT")
        self.assertEqual(candidate.validation_payload["symbol"], "AAPL")
        self.assertEqual(candidate.validation_payload["side"], "BUY")

    def test_positive_z_candidate_is_watch_only_for_long_module(self) -> None:
        plan = build_plan(
            [
                {
                    "symbol": "MSFT",
                    "last_price": 200.0,
                    "diagnostics": {
                        "verdict": "watchlist",
                        "mean_reversion_score": 55.0,
                        "latest_z_score": 1.8,
                    },
                }
            ],
            diagnostics_path=Path("diagnostics.json"),
            entry_z=1.0,
        )

        self.assertEqual(plan.validate_payload_count, 0)
        self.assertEqual(plan.candidates[0].action, "WATCH")

    def test_rejected_diagnostics_do_not_create_payload(self) -> None:
        plan = build_plan(
            [
                {
                    "symbol": "TSLA",
                    "last_price": 250.0,
                    "diagnostics": {
                        "verdict": "reject",
                        "mean_reversion_score": 5.0,
                        "latest_z_score": -3.0,
                    },
                }
            ],
            diagnostics_path=Path("diagnostics.json"),
        )

        self.assertEqual(plan.candidates[0].action, "REJECT")
        self.assertIsNone(plan.candidates[0].validation_payload)

    def test_load_and_write_plan_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            diagnostics_path = Path(tmp) / "diagnostics.json"
            output = Path(tmp) / "plan.json"
            diagnostics_path.write_text(
                json.dumps(
                    [
                        {
                            "symbol": "AAPL",
                            "last_price": 100.0,
                            "diagnostics": {
                                "verdict": "watchlist",
                                "mean_reversion_score": 50.0,
                                "latest_z_score": -1.2,
                            },
                        }
                    ]
                ),
                encoding="utf-8",
            )

            plan = build_plan(load_diagnostics(diagnostics_path), diagnostics_path=diagnostics_path)
            write_plan(plan, output)

            self.assertTrue(output.exists())
            self.assertIn("VALIDATE_BUY_LIMIT", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
