import csv
import tempfile
import unittest
from pathlib import Path

from research.quote_quality_report import build_quote_quality_report, write_quote_quality_json, write_quote_quality_markdown


class QuoteQualityReportTests(unittest.TestCase):
    def test_static_last_prices_are_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "quotes.csv"
            self._write_rows(path, [100.0] * 12)

            report = build_quote_quality_report(path)

            self.assertEqual(report.status, "static_last_prices")
            self.assertEqual(report.symbols[0].verdict, "static_last_price")
            self.assertTrue(any("Do not force" in action for action in report.next_actions))

    def test_moving_prices_are_usable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "quotes.csv"
            self._write_rows(path, [100.0 + index * 0.1 for index in range(12)])

            report = build_quote_quality_report(path)

            self.assertEqual(report.status, "usable_quote_movement_detected")
            self.assertEqual(report.symbols[0].verdict, "usable_for_research")

    def test_writers_create_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "quotes.csv"
            self._write_rows(csv_path, [100.0] * 12)
            report = build_quote_quality_report(csv_path)
            write_quote_quality_json(report, root / "quality.json")
            write_quote_quality_markdown(report, root / "quality.md")

            self.assertTrue((root / "quality.json").exists())
            self.assertIn("Quote Quality Report", (root / "quality.md").read_text(encoding="utf-8"))

    @staticmethod
    def _write_rows(path: Path, prices: list[float]) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["sample", "symbol", "last", "close", "spread", "volume"])
            writer.writeheader()
            for index, price in enumerate(prices):
                writer.writerow(
                    {
                        "sample": index,
                        "symbol": "AAPL",
                        "last": price,
                        "close": price,
                        "spread": 0.05,
                        "volume": index,
                    }
                )


if __name__ == "__main__":
    unittest.main()
