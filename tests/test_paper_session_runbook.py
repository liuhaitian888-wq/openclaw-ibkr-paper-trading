import tempfile
import unittest
from pathlib import Path

from research.paper_session_runbook import build_runbook, render_markdown, write_runbook_json, write_runbook_markdown
from tests.test_paper_environment_audit import READY_HEALTH


BLOCKED_AUDIT = {
    "status": "blocked",
    "api_url": "http://127.0.0.1:8787",
    "items": [
        {
            "name": "paper_mode",
            "status": "fail",
            "required": True,
            "detail": "TRADING_MODE=DRY_RUN",
        },
        {
            "name": "api_health_reachable",
            "status": "fail",
            "required": True,
            "detail": "Trading API /health unavailable",
        },
    ],
}


READY_AUDIT = {
    "status": "ready_for_one_share_paper_trial",
    "api_url": "http://127.0.0.1:8787",
    "health": READY_HEALTH,
    "items": [],
}


class PaperSessionRunbookTests(unittest.TestCase):
    def test_blocked_runbook_lists_blockers_and_safe_commands(self) -> None:
        runbook = build_runbook(
            BLOCKED_AUDIT,
            {"status": "environment_blocked", "reason": "environment audit status is blocked"},
        )

        self.assertEqual(runbook.status, "environment_blocked")
        self.assertTrue(any("paper_mode" in blocker for blocker in runbook.blockers))
        command_names = [command.name for command in runbook.commands]
        self.assertIn("Open Mode Control", command_names)
        self.assertIn("Audit Environment", command_names)
        self.assertIn("Guarded Dry Run", command_names)
        self.assertIn("Simulated Ready Rehearsal", command_names)
        self.assertIn("Build Preflight Checklist", command_names)
        self.assertIn("Monitor Readiness", command_names)
        self.assertIn("Build Runbook", command_names)
        self.assertIn("Reconcile Paper Trial", command_names)
        self.assertIn("Build Evidence Bundle", command_names)

    def test_ready_runbook_includes_validate_and_explicit_paper_commands(self) -> None:
        runbook = build_runbook(READY_AUDIT, {"status": "not_started"})

        self.assertEqual(runbook.status, "ready_to_run_guarded_validate")
        commands = {command.name: command.command for command in runbook.commands}
        self.assertIn("--submit-validate", commands["Guarded Validate"])
        self.assertIn("PAPER_ONLY_1_SHARE", commands["Explicit One-Share Paper"])

    def test_markdown_and_json_are_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runbook = build_runbook(BLOCKED_AUDIT)
            write_runbook_json(runbook, root / "runbook.json")
            write_runbook_markdown(runbook, root / "runbook.md")

            self.assertTrue((root / "runbook.json").exists())
            markdown = (root / "runbook.md").read_text(encoding="utf-8")
            self.assertIn("Paper Trial Session Runbook", markdown)
            self.assertEqual(markdown, render_markdown(runbook))


if __name__ == "__main__":
    unittest.main()
