import csv
import tempfile
import unittest
from pathlib import Path

from research.mean_reversion_diagnostics import (
    diagnose_prices,
    diagnose_symbol_prices,
    read_prices_csv,
    write_report,
)


class MeanReversionDiagnosticsTests(unittest.TestCase):
    def test_oscillating_series_is_research_candidate(self) -> None:
        prices = [100.0, 102.0, 98.0, 101.5, 98.5, 101.0, 99.0, 100.8, 99.2, 100.5] * 4

        result = diagnose_prices(prices, z_window=10)

        self.assertIn(result.verdict, {"watchlist", "research_candidate"})
        self.assertIsNotNone(result.half_life_periods)
        self.assertIsNotNone(result.hurst_exponent)
        self.assertLess(result.variance_ratio or 1.0, 1.0)

    def test_trending_series_is_rejected(self) -> None:
        prices = [100.0 + index for index in range(40)]

        result = diagnose_prices(prices)

        self.assertEqual(result.verdict, "reject")
        self.assertLess(result.mean_reversion_score, 45.0)

    def test_csv_reader_groups_prices_by_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prices.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["symbol", "close"])
                writer.writeheader()
                writer.writerow({"symbol": "AAPL", "close": "100"})
                writer.writerow({"symbol": "AAPL", "close": "101"})
                writer.writerow({"symbol": "MSFT", "close": "200"})

            grouped = read_prices_csv(path)

        self.assertEqual(grouped["AAPL"], [100.0, 101.0])
        self.assertEqual(grouped["MSFT"], [200.0])

    def test_write_report_creates_json_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.json"
            item = diagnose_symbol_prices("AAPL", [100.0, 102.0, 98.0, 101.0, 99.0] * 3)

            write_report([item], output)

            self.assertTrue(output.exists())
            self.assertIn("AAPL", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
