import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from research.full_paper_trial_pipeline import FullPaperTrialPipelineConfig, run_full_pipeline
from trading.market_data import Quote


class PullbackQuoteSource:
    def __init__(self) -> None:
        self.last_errors: list[str] = []
        self.calls = 0
        self.values = [
            100.0,
            102.0,
            98.0,
            101.5,
            98.5,
            101.0,
            99.0,
            100.8,
            99.2,
            97.5,
        ]

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


class FullPaperTrialPipelineTests(unittest.TestCase):
    def test_full_pipeline_writes_all_reports_without_submitting_paper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = run_full_pipeline(
                PullbackQuoteSource(),
                FullPaperTrialPipelineConfig(
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
                    full_pipeline_report=root / "full.json",
                    z_window=10,
                    entry_z=0.1,
                ),
            )

            self.assertEqual(report.quote_rows_written, 20)
            self.assertEqual(report.diagnostic_count, 1)
            self.assertEqual(report.validate_payload_count, 1)
            self.assertEqual(report.status, "validate_required")
            self.assertEqual(report.readiness_status, "validate_required")
            self.assertEqual(report.gate_status, "blocked")
            self.assertFalse(report.paper_submitted)
            for name in [
                "quotes.csv",
                "recorder.json",
                "diagnostics.json",
                "paper_plan.json",
                "ibkr_pipeline.json",
                "readiness.json",
                "gate.json",
                "full.json",
            ]:
                self.assertTrue((root / name).exists(), name)
            full_payload = json.loads((root / "full.json").read_text(encoding="utf-8"))
            self.assertEqual(full_payload["source"], "full_paper_trial_pipeline")


if __name__ == "__main__":
    unittest.main()
