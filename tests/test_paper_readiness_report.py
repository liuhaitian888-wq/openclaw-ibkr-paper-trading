import json
import tempfile
import unittest
from pathlib import Path

from research.paper_readiness_report import build_readiness_report, load_plan, write_readiness_report


class PaperReadinessReportTests(unittest.TestCase):
    def test_report_requires_validate_before_paper(self) -> None:
        report = build_readiness_report(
            {
                "candidates": [
                    {
                        "action": "VALIDATE_BUY_LIMIT",
                        "validation_payload": {"symbol": "AAPL"},
                        "validation_result": None,
                    },
                    {"action": "WATCH", "validation_payload": None},
                ]
            },
            plan_path=Path("plan.json"),
        )

        self.assertEqual(report.status, "validate_required")
        self.assertEqual(report.validate_payload_count, 1)
        self.assertEqual(report.validate_approved_count, 0)

    def test_report_marks_manual_review_after_all_validates_pass(self) -> None:
        report = build_readiness_report(
            {
                "candidates": [
                    {
                        "action": "VALIDATE_BUY_LIMIT",
                        "validation_payload": {"symbol": "AAPL"},
                        "validation_result": {"approved": True},
                    }
                ]
            },
            plan_path=Path("plan.json"),
        )

        self.assertEqual(report.status, "ready_for_manual_paper_review")
        self.assertEqual(report.validate_approved_count, 1)
        self.assertTrue(any("one 1-share paper order" in step for step in report.required_operator_steps))

    def test_load_and_write_report_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "plan.json"
            output = Path(tmp) / "readiness.json"
            plan_path.write_text(json.dumps({"candidates": []}), encoding="utf-8")

            report = build_readiness_report(load_plan(plan_path), plan_path=plan_path)
            write_readiness_report(report, output)

            self.assertTrue(output.exists())
            self.assertIn("not_ready_for_paper", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
