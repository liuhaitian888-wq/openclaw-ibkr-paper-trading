import csv
import tempfile
import unittest
from pathlib import Path

from trading.pool_manager import build_pool_manager_report


class PoolManagerTests(unittest.TestCase):
    def test_builds_six_layers_and_forces_positions_into_monitor_pool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "universe.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["symbol", "name", "sector", "tags", "enabled", "value_score"],
                )
                writer.writeheader()
                writer.writerow({"symbol": "PFE", "name": "Pfizer", "sector": "Healthcare", "tags": "", "enabled": "true", "value_score": "70"})
                writer.writerow({"symbol": "BAD", "name": "Blocked", "sector": "Tech", "tags": "", "enabled": "false", "value_score": "20"})

            report = build_pool_manager_report(
                universe_file=path,
                position_guard={"symbols": [{"symbol": "HELD", "position_qty": 3, "open_buy_orders": 0, "open_sell_orders": 0}]},
                latest_agent={"monitor_symbols": ["PFE"], "research_tasks": [{"symbol": "PFE", "reason": "test mover"}]},
            )

        pools = {row["pool_name"] for row in report["membership"]["records"]}
        self.assertTrue({"security_master", "discovery_universe", "tradable_universe", "stream_eligible_pool", "monitor_pool", "hot_pool", "trade_pool"}.issubset(pools))
        monitor_symbols = {row["symbol"] for row in report["membership"]["records"] if row["pool_name"] == "monitor_pool"}
        self.assertIn("HELD", monitor_symbols)
        blocked = [row for row in report["membership"]["records"] if row["symbol"] == "BAD" and row["excluded"]]
        self.assertTrue(blocked)
        self.assertTrue(report["report_only"])


if __name__ == "__main__":
    unittest.main()
