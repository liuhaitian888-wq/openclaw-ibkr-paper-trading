import tempfile
import unittest
from pathlib import Path

from trading.strategy import ValueFilterConfig, ValuePoolFilter
from trading.universe import (
    UniverseSelectionConfig,
    default_universe_symbols,
    load_universe,
    select_universe,
    symbols_csv,
)


class UniverseTests(unittest.TestCase):
    def test_default_universe_loads_large_enabled_pool(self) -> None:
        symbols = default_universe_symbols()

        self.assertIn("AAPL", symbols)
        self.assertIn("MSFT", symbols)
        self.assertGreater(len(symbols), 50)

    def test_select_universe_intersects_gateway_allowlist(self) -> None:
        entries = load_universe()
        selection = select_universe(
            entries,
            ValuePoolFilter(ValueFilterConfig()),
            UniverseSelectionConfig(max_symbols=10),
            gateway_allowed_symbols=["AAPL", "MSFT", "ZZZZ"],
        )

        self.assertEqual(set(selection.symbols), {"AAPL", "MSFT"})

    def test_symbols_csv_deduplicates_and_normalizes(self) -> None:
        self.assertEqual(symbols_csv(["aapl", "MSFT", "AAPL"]), "AAPL,MSFT")

    def test_loader_respects_disabled_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "universe.csv"
            path.write_text(
                "symbol,name,exchange,sector,enabled,tags,average_volume\n"
                "AAPL,Apple,NASDAQ,Technology,true,mega,1000000\n"
                "ZZZZ,Disabled,NASDAQ,Technology,false,test,1000000\n",
                encoding="utf-8",
            )
            entries = load_universe(path)
            selection = select_universe(
                entries,
                ValuePoolFilter(ValueFilterConfig()),
            )

        self.assertIn("AAPL", selection.symbols)
        self.assertNotIn("ZZZZ", selection.symbols)


if __name__ == "__main__":
    unittest.main()
