import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from research.paper_candidate_hunt import PaperCandidateHuntConfig, run_candidate_hunt
from tests.test_paper_environment_audit import READY_HEALTH, make_settings
from trading.market_data import Quote


class SequenceQuoteSource:
    last_errors: list[str] = []

    def __init__(self, prices: list[float]) -> None:
        self._prices = prices
        self._calls = 0

    def get_quotes(self, symbols: list[str]) -> list[Quote]:
        price = self._prices[self._calls % len(self._prices)]
        self._calls += 1
        return [
            Quote(
                symbol=symbol,
                last=price,
                bid=price - 0.01,
                ask=price + 0.01,
                timestamp=datetime.now(timezone.utc),
                source="test",
                volume=100 + self._calls,
            )
            for symbol in symbols
        ]


class PaperCandidateHuntTests(unittest.TestCase):
    def test_hunt_stops_when_validate_payload_is_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def source_factory(attempt: int) -> SequenceQuoteSource:
                if attempt == 1:
                    return SequenceQuoteSource([100.0] * 12)
                return SequenceQuoteSource([100.0, 102.0, 98.0, 101.5, 98.5, 101.0, 99.0, 100.8, 99.2, 97.5] * 2)

            with patch("research.paper_candidate_hunt.PROJECT_ROOT", root), patch(
                "research.paper_validation_plan._request_json",
                return_value={"approved": True, "status": "validated"},
            ):
                report = run_candidate_hunt(
                    make_settings(tmp, trading_mode="PAPER", allow_paper_transmit=True, trade_session_token="ok"),
                    PaperCandidateHuntConfig(
                        symbols=["AAPL"],
                        max_attempts=2,
                        pause_seconds=0.0,
                        samples=20,
                        interval_seconds=0.0,
                        output_report=root / "hunt.json",
                        quotes_csv=root / "quotes.csv",
                        quote_quality_json=root / "quality.json",
                        quote_quality_md=root / "quality.md",
                        api_key="test-key",
                        recorder_report=root / "recorder.json",
                        diagnostics_report=root / "diagnostics.json",
                        paper_plan_report=root / "plan.json",
                        ibkr_pipeline_report=root / "ibkr_pipeline.json",
                        readiness_report=root / "readiness.json",
                        execution_gate_report=root / "gate.json",
                        full_pipeline_report=root / "full.json",
                        environment_audit_report=root / "environment.json",
                        guarded_session_report=root / "guarded.json",
                    ),
                    quote_source_factory=source_factory,
                    health_provider=lambda: (READY_HEALTH, ""),
                )

            self.assertEqual(report.status, "validate_payload_found")
            self.assertEqual(len(report.attempts), 2)
            self.assertGreater(report.attempts[-1].validate_payload_count, 0)
            self.assertTrue((root / "hunt.json").exists())

    def test_hunt_reports_static_quotes_without_forcing_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("research.paper_candidate_hunt.PROJECT_ROOT", root):
                report = run_candidate_hunt(
                    make_settings(tmp, trading_mode="PAPER", allow_paper_transmit=True, trade_session_token="ok"),
                    PaperCandidateHuntConfig(
                        symbols=["AAPL"],
                        max_attempts=1,
                        pause_seconds=0.0,
                        samples=12,
                        interval_seconds=0.0,
                        output_report=root / "hunt.json",
                        quotes_csv=root / "quotes.csv",
                        quote_quality_json=root / "quality.json",
                        quote_quality_md=root / "quality.md",
                        api_key="test-key",
                        recorder_report=root / "recorder.json",
                        diagnostics_report=root / "diagnostics.json",
                        paper_plan_report=root / "plan.json",
                        ibkr_pipeline_report=root / "ibkr_pipeline.json",
                        readiness_report=root / "readiness.json",
                        execution_gate_report=root / "gate.json",
                        full_pipeline_report=root / "full.json",
                        environment_audit_report=root / "environment.json",
                        guarded_session_report=root / "guarded.json",
                    ),
                    quote_source_factory=lambda attempt: SequenceQuoteSource([100.0] * 12),
                    health_provider=lambda: (READY_HEALTH, ""),
                )

            self.assertEqual(report.status, "no_candidate_static_quotes")
            self.assertEqual(report.attempts[-1].validate_payload_count, 0)


if __name__ == "__main__":
    unittest.main()
