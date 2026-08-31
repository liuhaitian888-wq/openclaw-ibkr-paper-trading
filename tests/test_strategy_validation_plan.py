import csv
import tempfile
import unittest
from pathlib import Path

from research.strategy_validation_plan import StrategyValidationPlanConfig, build_strategy_validation_plan


class StrategyValidationPlanTests(unittest.TestCase):
    def test_grid_pullback_creates_validate_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            quotes_csv = Path(tmp) / "quotes.csv"
            _write_quotes(
                quotes_csv,
                [
                    {"sample": "0", "symbol": "AAPL", "timestamp": "2026-07-08T00:00:00+00:00", "last": "100.00", "bid": "99.99", "ask": "100.01"},
                    {"sample": "1", "symbol": "AAPL", "timestamp": "2026-07-08T00:00:01+00:00", "last": "99.95", "bid": "99.94", "ask": "99.96"},
                ],
            )

            plan = build_strategy_validation_plan(
                StrategyValidationPlanConfig(
                    quotes_csv=quotes_csv,
                    grid_pct=0.0002,
                    max_limit_price=400.0,
                    max_spread_bps=5.0,
                    min_confidence=0.05,
                )
            )

        payloads = [candidate for candidate in plan.candidates if candidate.validation_payload is not None]
        self.assertEqual(plan.source, "strategy_validation_plan")
        self.assertGreaterEqual(len(payloads), 1)
        self.assertEqual(payloads[0].validation_payload["symbol"], "AAPL")
        self.assertEqual(payloads[0].validation_payload["side"], "BUY")

    def test_wide_spread_rejects_buy_signal_before_validate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            quotes_csv = Path(tmp) / "quotes.csv"
            _write_quotes(
                quotes_csv,
                [
                    {"sample": "0", "symbol": "AAPL", "timestamp": "2026-07-08T00:00:00+00:00", "last": "100.00", "bid": "99.00", "ask": "101.00"},
                    {"sample": "1", "symbol": "AAPL", "timestamp": "2026-07-08T00:00:01+00:00", "last": "99.90", "bid": "98.90", "ask": "100.90"},
                ],
            )

            plan = build_strategy_validation_plan(
                StrategyValidationPlanConfig(
                    quotes_csv=quotes_csv,
                    grid_pct=0.0002,
                    max_limit_price=400.0,
                    max_spread_bps=5.0,
                    min_confidence=0.05,
                )
            )

        self.assertEqual(plan.validate_payload_count, 0)
        self.assertTrue(any(candidate.action == "REJECT" for candidate in plan.candidates))


def _write_quotes(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["sample", "symbol", "timestamp", "last", "bid", "ask"])
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
