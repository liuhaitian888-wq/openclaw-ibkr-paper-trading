import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from research.ibkr_mean_reversion_pipeline import IbkrMeanReversionPipelineConfig, run_pipeline
from trading.market_data import Quote


class OscillatingQuoteSource:
    def __init__(self) -> None:
        self.last_errors: list[str] = []
        self.calls = 0
        self.values = [100.0, 102.0, 98.0, 101.5, 98.5, 101.0, 99.0, 100.8, 99.2, 100.5]

    def get_quotes(self, symbols: list[str]) -> list[Quote]:
        price = self.values[self.calls % len(self.values)]
        self.calls += 1
        return [
            Quote(
                symbol=symbol,
                last=price,
                bid=price - 0.02,
                ask=price + 0.02,
                timestamp=datetime.now(timezone.utc),
                source="fake_ibkr",
                volume=1000,
            )
            for symbol in symbols
        ]


class IbkrMeanReversionPipelineTests(unittest.TestCase):
    def test_pipeline_records_quotes_and_writes_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = run_pipeline(
                OscillatingQuoteSource(),
                IbkrMeanReversionPipelineConfig(
                    symbols=["AAPL"],
                    samples=20,
                    interval_seconds=0.0,
                    quotes_csv=root / "quotes.csv",
                    recorder_report=root / "recorder.json",
                    diagnostics_report=root / "diagnostics.json",
                    paper_plan_report=root / "paper_plan.json",
                    pipeline_report=root / "pipeline.json",
                    z_window=10,
                    entry_z=1.0,
                ),
            )

            self.assertEqual(report.quote_rows_written, 20)
            self.assertEqual(report.diagnostic_count, 1)
            self.assertEqual(report.paper_plan_candidate_count, 1)
            self.assertTrue((root / "quotes.csv").exists())
            self.assertTrue((root / "diagnostics.json").exists())
            self.assertTrue((root / "paper_plan.json").exists())
            payload = json.loads((root / "pipeline.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["source"], "ibkr_mean_reversion_pipeline")
            self.assertTrue(
                {"watchlist", "research_candidate"}.intersection(payload["verdict_counts"])
            )
            self.assertIn("paper_plan_validate_payload_count", payload)


if __name__ == "__main__":
    unittest.main()
