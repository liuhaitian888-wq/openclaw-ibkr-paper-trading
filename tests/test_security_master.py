import csv
import tempfile
import unittest
from pathlib import Path

from trading.security_master import build_security_master_report


class SecurityMasterTests(unittest.TestCase):
    def test_builds_security_master_from_universe_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "universe.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["symbol", "name", "sector", "tags", "enabled"])
                writer.writeheader()
                writer.writerow({"symbol": "PFE", "name": "Pfizer", "sector": "Healthcare", "tags": "large_cap", "enabled": "true"})

            report = build_security_master_report(path)

        self.assertEqual(report["source"], "security_master")
        self.assertEqual(report["records"][0]["symbol"], "PFE")
        self.assertEqual(report["records"][0]["asset_type"], "STK")
        self.assertIn("last_updated_at", report["records"][0])


if __name__ == "__main__":
    unittest.main()
