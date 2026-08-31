import unittest

from research.paper_trial_preflight_checklist import build_preflight_checklist
from tests.test_paper_environment_audit import READY_HEALTH


READY_AUDIT = {
    "status": "ready_for_one_share_paper_trial",
    "health": READY_HEALTH,
    "items": [],
}

READY_RUNBOOK = {
    "status": "ready_to_run_guarded_validate",
}

CLEAN_REHEARSAL = {
    "status": "completed",
    "ibkr_market_data_used": False,
    "trading_api_validate_used": False,
    "paper_order_used": False,
}


class PaperTrialPreflightChecklistTests(unittest.TestCase):
    def test_ready_checklist_allows_validate_only_window(self) -> None:
        checklist = build_preflight_checklist(READY_AUDIT, READY_RUNBOOK, rehearsal=CLEAN_REHEARSAL)

        self.assertEqual(checklist.status, "ready_for_validate_only_window")
        self.assertEqual(checklist.next_allowed_action, "run_guarded_validate_only")
        self.assertTrue(all(check.status == "pass" for check in checklist.machine_checks))
        self.assertTrue(any("--submit-validate" in command for command in checklist.commands))

    def test_blocked_audit_blocks_real_ibkr_window(self) -> None:
        checklist = build_preflight_checklist(
            {"status": "blocked"},
            {"status": "environment_blocked"},
            rehearsal=CLEAN_REHEARSAL,
        )

        self.assertEqual(checklist.status, "blocked_before_real_ibkr_window")
        self.assertEqual(checklist.next_allowed_action, "fix_environment_and_refresh_reports")
        failures = {check.name for check in checklist.machine_checks if check.status == "fail"}
        self.assertIn("environment_audit_ready", failures)
        self.assertFalse(any("--submit-validate" in command for command in checklist.commands))

    def test_missing_rehearsal_requires_attention_after_ready_audit(self) -> None:
        checklist = build_preflight_checklist(READY_AUDIT, READY_RUNBOOK, rehearsal=None)

        self.assertEqual(checklist.status, "attention_required_before_real_ibkr_window")
        failures = {check.name for check in checklist.machine_checks if check.status == "fail"}
        self.assertEqual(failures, {"safe_rehearsal_completed"})


if __name__ == "__main__":
    unittest.main()
