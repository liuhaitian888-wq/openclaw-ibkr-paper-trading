import tempfile
import unittest
from pathlib import Path

from research.paper_trial_evidence_bundle import (
    build_evidence_bundle,
    write_evidence_bundle,
    write_evidence_markdown,
)


class PaperTrialEvidenceBundleTests(unittest.TestCase):
    def test_blocked_environment_classifies_before_paper_window(self) -> None:
        bundle = build_evidence_bundle(
            audit={"status": "blocked", "next_steps": ["Start TRADE_LOCK."]},
            guarded_session={"status": "environment_blocked"},
            runbook={"status": "environment_blocked"},
            reconciliation={"status": "no_paper_submission"},
            artifact_paths={},
        )

        self.assertEqual(bundle.stage, "blocked_before_paper_window")
        self.assertIn("Start TRADE_LOCK.", bundle.next_actions)

    def test_submitted_without_reconciliation_needs_reconciliation(self) -> None:
        bundle = build_evidence_bundle(
            audit={"status": "ready_for_one_share_paper_trial"},
            guarded_session={"status": "paper_submitted"},
            runbook={"status": "paper_submitted_review_required"},
            reconciliation={"status": "reconciliation_incomplete"},
            artifact_paths={},
        )

        self.assertEqual(bundle.stage, "paper_submitted_needs_reconciliation")

    def test_ready_execution_gate_classifies_explicit_paper_submit(self) -> None:
        bundle = build_evidence_bundle(
            audit={"status": "ready_for_one_share_paper_trial"},
            guarded_session={"status": "completed_without_paper_candidate"},
            runbook={"status": "ready_to_run_guarded_validate"},
            readiness={"status": "ready_for_manual_paper_review"},
            execution_gate={"status": "ready_for_explicit_paper_submit"},
            reconciliation={"status": "no_paper_submission"},
            artifact_paths={},
        )

        self.assertEqual(bundle.stage, "ready_for_explicit_paper_submit")

    def test_reconciled_stage_requires_reconciled_report(self) -> None:
        bundle = build_evidence_bundle(
            audit={"status": "ready_for_one_share_paper_trial"},
            guarded_session={"status": "paper_submitted"},
            runbook={"status": "paper_submitted_review_required"},
            reconciliation={"status": "reconciled"},
            artifact_paths={},
        )

        self.assertEqual(bundle.stage, "paper_reconciled")

    def test_reviewed_gate_reconciled_stage_does_not_require_guarded_session_submission(self) -> None:
        bundle = build_evidence_bundle(
            audit={"status": "ready_for_one_share_paper_trial"},
            guarded_session={"status": "completed_without_paper_candidate"},
            runbook={"status": "ready_to_run_guarded_validate"},
            readiness={"status": "ready_for_manual_paper_review"},
            execution_gate={"status": "submitted"},
            reconciliation={"status": "reconciled"},
            artifact_paths={},
        )

        self.assertEqual(bundle.stage, "paper_reconciled")

    def test_writers_create_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = build_evidence_bundle(
                audit={"status": "blocked"},
                guarded_session=None,
                runbook=None,
                reconciliation=None,
                artifact_paths={"audit": root / "missing.json"},
            )
            write_evidence_bundle(bundle, root / "bundle.json")
            write_evidence_markdown(bundle, root / "bundle.md")

            self.assertTrue((root / "bundle.json").exists())
            self.assertIn("Paper Trial Evidence Bundle", (root / "bundle.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
