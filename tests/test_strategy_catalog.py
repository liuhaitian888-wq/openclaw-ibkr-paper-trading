import tempfile
import unittest
from pathlib import Path

from research.strategy_catalog import build_strategy_catalog, write_strategy_catalog_json, write_strategy_catalog_markdown


class StrategyCatalogTests(unittest.TestCase):
    def test_catalog_covers_current_strategy_modules_and_books(self) -> None:
        catalog = build_strategy_catalog()

        names = {entry.name for entry in catalog.entries}
        self.assertEqual(
            names,
            {
                "dual_moving_average",
                "zscore_mean_reversion",
                "grid_rebalance",
                "lightgbm_style_baseline",
            },
        )
        all_sources = " ".join(" ".join(entry.book_sources) for entry in catalog.entries)
        self.assertIn("Ernest P. Chan, Quantitative Trading", all_sources)
        self.assertIn("Ernest P. Chan, Algorithmic Trading", all_sources)
        self.assertIn("Robert Carver, Systematic Trading", all_sources)
        self.assertIn("Marcos Lopez de Prado, Advances in Financial Machine Learning", all_sources)
        self.assertTrue(all(entry.risk_controls for entry in catalog.entries))
        self.assertTrue(all(entry.book_sources for entry in catalog.entries))
        self.assertTrue(all(entry.next_validation_steps for entry in catalog.entries))

    def test_writers_create_catalog_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = build_strategy_catalog()
            write_strategy_catalog_json(catalog, root / "catalog.json")
            write_strategy_catalog_markdown(catalog, root / "catalog.md")

            self.assertTrue((root / "catalog.json").exists())
            markdown = (root / "catalog.md").read_text(encoding="utf-8")
            self.assertIn("Strategy Catalog", markdown)
            self.assertIn("dual_moving_average", markdown)
            self.assertIn("Book Sources", markdown)


if __name__ == "__main__":
    unittest.main()
