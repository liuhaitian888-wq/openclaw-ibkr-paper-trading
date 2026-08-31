import tempfile
import unittest
from pathlib import Path

from research.project_completion_audit import build_completion_audit, write_completion_audit_json, write_completion_audit_markdown


CLEAN_REHEARSAL = {
    "status": "completed",
    "ibkr_market_data_used": False,
    "trading_api_validate_used": False,
    "paper_order_used": False,
}


class ProjectCompletionAuditTests(unittest.TestCase):
    def test_current_blocked_state_is_not_complete(self) -> None:
        audit = build_completion_audit(
            strategy_catalog={"status": "modular_catalog_ready"},
            preflight={"status": "blocked_before_real_ibkr_window", "next_allowed_action": "fix_environment_and_refresh_reports"},
            evidence_bundle={"stage": "blocked_before_paper_window"},
            readiness_monitor={"status": "waiting_for_real_ibkr_window"},
            rehearsal=CLEAN_REHEARSAL,
            full_pipeline=None,
            quote_quality=None,
        )

        self.assertEqual(audit.status, "incomplete_real_ibkr_evidence_missing")
        statuses = {item.name: item.status for item in audit.requirements}
        self.assertEqual(statuses["book_methodology_mapped_to_modules"], "complete")
        self.assertEqual(statuses["safe_simulated_ready_rehearsal"], "complete")
        self.assertEqual(statuses["real_ibkr_window_ready"], "incomplete")
        self.assertTrue(any("TWS/IB Gateway paper" in item for item in audit.next_required_evidence))

    def test_reconciled_stage_can_complete_audit(self) -> None:
        audit = build_completion_audit(
            strategy_catalog={"status": "modular_catalog_ready"},
            preflight={"status": "ready_for_validate_only_window", "next_allowed_action": "run_guarded_validate_only"},
            evidence_bundle={"stage": "paper_reconciled"},
            readiness_monitor={"status": "ready_for_validate_only_window"},
            rehearsal=CLEAN_REHEARSAL,
            full_pipeline={"submitted_validate": True, "validate_payload_count": 1, "quote_rows_written": 12},
            quote_quality={"status": "usable_quote_movement_detected"},
        )

        self.assertEqual(audit.status, "complete")
        self.assertTrue(all(item.status == "complete" for item in audit.requirements))

    def test_writers_create_audit_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit = build_completion_audit(
                strategy_catalog={"status": "modular_catalog_ready"},
                preflight=None,
                evidence_bundle=None,
                readiness_monitor=None,
                rehearsal=None,
                full_pipeline=None,
                quote_quality=None,
            )
            write_completion_audit_json(audit, root / "audit.json")
            write_completion_audit_markdown(audit, root / "audit.md")

            self.assertTrue((root / "audit.json").exists())
            self.assertIn("Project Completion Audit", (root / "audit.md").read_text(encoding="utf-8"))

    def test_validate_attempt_without_payload_is_not_complete(self) -> None:
        audit = build_completion_audit(
            strategy_catalog={"status": "modular_catalog_ready"},
            preflight={"status": "ready_for_validate_only_window", "next_allowed_action": "run_guarded_validate_only"},
            evidence_bundle={"stage": "ready_for_guarded_validate"},
            readiness_monitor={"status": "ready_for_validate_only_window"},
            rehearsal=CLEAN_REHEARSAL,
            full_pipeline={
                "submitted_validate": True,
                "validate_payload_count": 0,
                "quote_rows_written": 36,
                "readiness_status": "not_ready_for_paper",
            },
            quote_quality={"status": "static_last_prices"},
        )

        statuses = {item.name: item.status for item in audit.requirements}
        details = {item.name: item.detail for item in audit.requirements}
        self.assertEqual(statuses["real_ibkr_quote_capture_done"], "complete")
        self.assertEqual(statuses["validate_only_results_done"], "incomplete")
        self.assertIn("validate_payload_count=0", details["validate_only_results_done"])
        self.assertIn("quote_quality_status=static_last_prices", details["validate_only_results_done"])


if __name__ == "__main__":
    unittest.main()
