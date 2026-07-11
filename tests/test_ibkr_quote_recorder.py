import csv
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from research.ibkr_quote_recorder import QuoteRecorderConfig, record_quotes
from trading.market_data import Quote


class FakeQuoteSource:
    def __init__(self) -> None:
        self.last_errors: list[str] = []
        self.calls = 0

    def get_quotes(self, symbols: list[str]) -> list[Quote]:
        self.calls += 1
        now = datetime.now(timezone.utc)
        return [
            Quote(
                symbol=symbol,
                last=100.0 + self.calls,
                bid=99.95 + self.calls,
                ask=100.05 + self.calls,
                timestamp=now,
                source="fake_ibkr",
                volume=1000 + self.calls,
            )
            for symbol in symbols
        ]


class IbkrQuoteRecorderTests(unittest.TestCase):
    def test_record_quotes_writes_research_csv_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_csv = Path(tmp) / "quotes.csv"
            output_report = Path(tmp) / "report.json"
            source = FakeQuoteSource()

            report = record_quotes(
                source,
                QuoteRecorderConfig(
                    symbols=["AAPL", "MSFT"],
                    samples=2,
                    interval_seconds=0.0,
                    output_csv=output_csv,
                    output_report=output_report,
                ),
            )

            self.assertEqual(report.quote_rows_written, 4)
            self.assertEqual(source.calls, 2)
            self.assertTrue(output_report.exists())
            with output_csv.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 4)
            self.assertEqual(rows[0]["symbol"], "AAPL")
            self.assertEqual(rows[0]["close"], "101.0")
            self.assertEqual(rows[0]["quote_source"], "fake_ibkr")

    def test_record_quotes_requires_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                record_quotes(
                    FakeQuoteSource(),
                    QuoteRecorderConfig(
                        symbols=[],
                        output_csv=Path(tmp) / "quotes.csv",
                        output_report=Path(tmp) / "report.json",
                    ),
                )


if __name__ == "__main__":
    unittest.main()
