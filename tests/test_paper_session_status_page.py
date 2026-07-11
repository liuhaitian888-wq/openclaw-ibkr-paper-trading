import tempfile
import unittest
from pathlib import Path

from research.paper_session_status_page import render_status_page, write_status_page


RUNBOOK = {
    "status": "environment_blocked",
    "summary": "The machine is not ready.",
    "created_at": "2026-07-07T23:00:00+00:00",
    "environment_status": "blocked",
    "guarded_session_status": "environment_blocked",
    "blockers": ["paper_mode: TRADING_MODE=DRY_RUN"],
    "operator_steps": ["Open TWS paper."],
    "commands": [
        {
            "name": "Audit Environment",
            "purpose": "Regenerate the readiness report.",
            "command": ".venv313/bin/python scripts/audit_paper_trading_readiness.py",
        }
    ],
    "artifacts": {"runbook": "reports/paper_session_runbook.json"},
}


class PaperSessionStatusPageTests(unittest.TestCase):
    def test_render_status_page_contains_core_sections(self) -> None:
        html = render_status_page(RUNBOOK)

        self.assertIn("Paper Trial Status", html)
        self.assertIn("environment_blocked", html)
        self.assertIn("Audit Environment", html)
        self.assertIn("paper_mode: TRADING_MODE=DRY_RUN", html)

    def test_write_status_page_creates_html_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "status.html"
            write_status_page(RUNBOOK, output)

            self.assertTrue(output.exists())
            self.assertIn("<!doctype html>", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
