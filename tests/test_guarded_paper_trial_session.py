import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from research.guarded_paper_trial_session import GuardedPaperTrialSessionConfig, run_guarded_session
from tests.test_paper_environment_audit import READY_HEALTH, make_settings
from trading.market_data import Quote


class PullbackQuoteSource:
    def __init__(self) -> None:
        self.last_errors: list[str] = []
        self.calls = 0
        self.values = [100.0, 102.0, 98.0, 101.5, 98.5, 101.0, 99.0, 100.8, 99.2, 97.5]

    def get_quotes(self, symbols: list[str]) -> list[Quote]:
        price = self.values[self.calls % len(self.values)]
        self.calls += 1
        return [
            Quote(
                symbol=symbol,
                last=price,
                bid=price - 0.01,
                ask=price + 0.01,
                timestamp=datetime.now(timezone.utc),
                source="fake_ibkr",
                volume=1000,
            )
            for symbol in symbols
        ]


def guarded_config(root: Path) -> GuardedPaperTrialSessionConfig:
    return GuardedPaperTrialSessionConfig(
        symbols=["AAPL"],
        samples=20,
        interval_seconds=0.0,
        quotes_csv=root / "quotes.csv",
        recorder_report=root / "recorder.json",
        diagnostics_report=root / "diagnostics.json",
        paper_plan_report=root / "paper_plan.json",
        ibkr_pipeline_report=root / "ibkr_pipeline.json",
        readiness_report=root / "readiness.json",
        execution_gate_report=root / "gate.json",
        full_pipeline_report=root / "full_pipeline.json",
        environment_audit_report=root / "environment.json",
        guarded_session_report=root / "guarded.json",
        z_window=10,
        entry_z=0.1,
    )


class GuardedPaperTrialSessionTests(unittest.TestCase):
    def test_blocks_before_pipeline_when_environment_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = run_guarded_session(
                PullbackQuoteSource(),
                make_settings(tmp),
                health=None,
                api_error="connection refused",
                config=guarded_config(root),
            )

            self.assertEqual(report.status, "environment_blocked")
            self.assertEqual(report.environment_status, "blocked")
            self.assertIsNone(report.pipeline_status)
            self.assertFalse((root / "quotes.csv").exists())
            self.assertTrue((root / "environment.json").exists())
            self.assertTrue((root / "guarded.json").exists())

    def test_ready_environment_runs_full_pipeline_without_paper_submit_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = run_guarded_session(
                PullbackQuoteSource(),
                make_settings(
                    tmp,
                    trading_mode="PAPER",
                    allow_paper_transmit=True,
                    trade_session_token="session-ok",
                ),
                health=READY_HEALTH,
                api_error="",
                config=guarded_config(root),
            )

            self.assertEqual(report.environment_status, "ready_for_one_share_paper_trial")
            self.assertEqual(report.status, "validate_required")
            self.assertEqual(report.pipeline_status, "validate_required")
            self.assertFalse(report.paper_submitted)
            self.assertTrue((root / "quotes.csv").exists())
            self.assertTrue((root / "full_pipeline.json").exists())


if __name__ == "__main__":
    unittest.main()
