import tempfile
import unittest
from pathlib import Path

from research.paper_trial_readiness_monitor import PaperTrialReadinessMonitorConfig, run_readiness_monitor
from tests.test_paper_environment_audit import READY_HEALTH, make_settings


CLEAN_REHEARSAL = {
    "status": "completed",
    "ibkr_market_data_used": False,
    "trading_api_validate_used": False,
    "paper_order_used": False,
}


class PaperTrialReadinessMonitorTests(unittest.TestCase):
    def test_monitor_waits_without_quote_or_order_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(tmp)
            (root / "rehearsal.json").write_text("{}\n", encoding="utf-8")

            report = run_readiness_monitor(
                settings,
                PaperTrialReadinessMonitorConfig(
                    max_attempts=1,
                    interval_seconds=0.0,
                    environment_audit_report=root / "audit.json",
                    runbook_json=root / "runbook.json",
                    runbook_md=root / "runbook.md",
                    rehearsal_report=root / "rehearsal.json",
                    preflight_json=root / "preflight.json",
                    preflight_md=root / "preflight.md",
                    monitor_json=root / "monitor.json",
                ),
                health_provider=lambda: (None, "connection refused"),
            )

            self.assertEqual(report.status, "waiting_for_real_ibkr_window")
            self.assertEqual(report.snapshots[-1].next_allowed_action, "fix_environment_and_refresh_reports")
            for name in ["audit.json", "runbook.json", "runbook.md", "preflight.json", "preflight.md", "monitor.json"]:
                self.assertTrue((root / name).exists(), name)

    def test_monitor_stops_when_preflight_becomes_validate_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(
                tmp,
                trading_mode="PAPER",
                allow_paper_transmit=True,
                trade_session_token="session-ok",
            )
            (root / "rehearsal.json").write_text(
                __import__("json").dumps(CLEAN_REHEARSAL),
                encoding="utf-8",
            )
            calls = {"count": 0}

            def provider():
                calls["count"] += 1
                return READY_HEALTH, ""

            report = run_readiness_monitor(
                settings,
                PaperTrialReadinessMonitorConfig(
                    max_attempts=3,
                    interval_seconds=0.0,
                    environment_audit_report=root / "audit.json",
                    runbook_json=root / "runbook.json",
                    runbook_md=root / "runbook.md",
                    rehearsal_report=root / "rehearsal.json",
                    preflight_json=root / "preflight.json",
                    preflight_md=root / "preflight.md",
                    monitor_json=root / "monitor.json",
                ),
                health_provider=provider,
            )

            self.assertEqual(calls["count"], 1)
            self.assertEqual(report.status, "ready_for_validate_only_window")
            self.assertEqual(report.snapshots[-1].next_allowed_action, "run_guarded_validate_only")


if __name__ == "__main__":
    unittest.main()
