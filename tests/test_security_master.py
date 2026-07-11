import csv
import tempfile
import unittest
from pathlib import Path

from trading.security_master import build_security_master_report, records_from_nasdaq_trader_rows


class SecurityMasterTests(unittest.TestCase):
    def test_builds_security_master_from_universe_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "universe.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["symbol", "name", "sector", "tags", "enabled"])
                writer.writeheader()
                writer.writerow({"symbol": "PFE", "name": "Pfizer", "sector": "Healthcare", "tags": "large_cap", "enabled": "true"})

            report = build_security_master_report(path, security_master_file=Path(tmp) / "missing_security_master.csv")

        self.assertEqual(report["source"], "security_master")
        self.assertEqual(report["records"][0]["symbol"], "PFE")
        self.assertEqual(report["records"][0]["asset_type"], "STK")
        self.assertIn("last_updated_at", report["records"][0])

    def test_persistent_security_master_takes_precedence_over_seed_universe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            seed = Path(tmp) / "universe.csv"
            master = Path(tmp) / "security_master.csv"
            seed.write_text("symbol,name,sector,tags,enabled\nPFE,Pfizer,Healthcare,,true\n", encoding="utf-8")
            master.write_text(
                "symbol,company_name,asset_type,primary_exchange,listing_exchange,currency,country,sector,industry,is_etf,is_adr,is_otc,is_test_issue,financial_status,listing_status,CIK,ibkr_conid,data_source,last_updated_at,blocked_reason,enabled\n"
                "AAPL,Apple,STK,NASDAQ,NASDAQ,USD,US,,,,false,false,false,,active,,,fixture,2026-01-01T00:00:00+00:00,,true\n",
                encoding="utf-8",
            )

            report = build_security_master_report(seed, security_master_file=master)

        self.assertEqual(report["source_mode"], "persistent_security_master")
        self.assertEqual(report["record_count"], 1)
        self.assertEqual(report["records"][0]["symbol"], "AAPL")

    def test_nasdaq_trader_rows_build_broad_master_records(self) -> None:
        rows = [
            {"Symbol": "AAPL", "Security Name": "Apple Inc. Common Stock", "Market Category": "Q", "Test Issue": "N", "Financial Status": "N", "ETF": "N"},
            {"ACT Symbol": "SPY", "Security Name": "SPDR S&P 500 ETF", "Exchange": "P", "Test Issue": "N", "ETF": "Y"},
        ]

        records = records_from_nasdaq_trader_rows(rows, source_name="fixture", now="2026-01-01T00:00:00+00:00")

        self.assertEqual([record.symbol for record in records], ["AAPL", "SPY"])
        self.assertEqual(records[0].asset_type, "STK")
        self.assertEqual(records[1].asset_type, "ETF")
        self.assertEqual(records[1].primary_exchange, "NYSE_ARCA")


if __name__ == "__main__":
    unittest.main()
