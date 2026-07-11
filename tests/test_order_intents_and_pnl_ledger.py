import sqlite3
import tempfile
import unittest
from pathlib import Path

from trading.order_intents import OrderIntent
from trading import execution_ledger_split
from trading.paper_audit_db import ensure_paper_automation_tables


class OrderIntentAndPnlLedgerTests(unittest.TestCase):
    def test_buy_intent_requires_buy_side(self) -> None:
        with self.assertRaises(ValueError):
            OrderIntent(
                intent_id="x",
                timestamp_utc="ts",
                cycle_id="cycle",
                symbol="AAPL",
                side="SELL",
                intent_type="ENTRY_BUY_LMT",
                order_type="LMT",
                source_module="paper_buy",
            )

    def test_options_plan_cannot_be_submitted_in_intent_task(self) -> None:
        with self.assertRaises(ValueError):
            OrderIntent(
                intent_id="x",
                timestamp_utc="ts",
                cycle_id="cycle",
                symbol="",
                side="OPTIONS",
                intent_type="OPTIONS_COVERED_COLLAR_PLAN",
                order_type="PLAN",
                source_module="options_execution",
                order_submitted=True,
            )

    def test_structured_pnl_tables_have_queryable_columns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "audit.sqlite3"
            ensure_paper_automation_tables(db)
            with sqlite3.connect(db) as con:
                account_cols = {row[1] for row in con.execute("PRAGMA table_info(account_pnl_snapshots)")}
                position_cols = {row[1] for row in con.execute("PRAGMA table_info(position_pnl_snapshots)")}
                daily_cols = {row[1] for row in con.execute("PRAGMA table_info(daily_pnl_summary)")}

        self.assertIn("net_liquidation", account_cols)
        self.assertIn("daily_pnl", account_cols)
        self.assertIn("symbol", position_cols)
        self.assertIn("unrealized_pnl", position_cols)
        self.assertIn("top_profit_symbol", daily_cols)
        self.assertIn("top_loss_symbol", daily_cols)

    def test_intents_route_to_split_ledgers_without_submissions(self) -> None:
        calls: list[tuple[str, dict]] = []
        original_insert_event = execution_ledger_split.insert_event

        def fake_insert_event(table: str, values: dict) -> None:
            calls.append((table, values))

        intents = [
            OrderIntent(
                intent_id="buy",
                timestamp_utc="ts",
                cycle_id="cycle",
                symbol="AAPL",
                side="BUY",
                intent_type="ENTRY_BUY_LMT",
                order_type="LMT",
                source_module="paper_buy",
            ),
            OrderIntent(
                intent_id="protective",
                timestamp_utc="ts",
                cycle_id="cycle",
                symbol="PFE",
                side="SELL",
                intent_type="PROTECTIVE_SELL_STP_LMT",
                order_type="STP LMT",
                source_module="position_protection",
            ),
            OrderIntent(
                intent_id="gap",
                timestamp_utc="ts",
                cycle_id="cycle",
                symbol="MSFT",
                side="SELL",
                intent_type="GAP_ESCAPE_SELL_LMT",
                order_type="LMT",
                source_module="gap_escape",
            ),
            OrderIntent(
                intent_id="profit",
                timestamp_utc="ts",
                cycle_id="cycle",
                symbol="META",
                side="SELL",
                intent_type="TAKE_PROFIT_SELL_LMT",
                order_type="LMT",
                source_module="profit_sell",
            ),
            OrderIntent(
                intent_id="event",
                timestamp_utc="ts",
                cycle_id="cycle",
                symbol="T",
                side="SELL",
                intent_type="EVENT_RISK_REDUCTION_SELL_LMT",
                order_type="LMT",
                source_module="event_risk_sell",
            ),
            OrderIntent(
                intent_id="options",
                timestamp_utc="ts",
                cycle_id="cycle",
                symbol="",
                side="OPTIONS",
                intent_type="OPTIONS_COVERED_COLLAR_PLAN",
                order_type="PLAN",
                source_module="options_execution",
            ),
        ]

        try:
            execution_ledger_split.insert_event = fake_insert_event
            execution_ledger_split.persist_intents(intents)
        finally:
            execution_ledger_split.insert_event = original_insert_event

        tables = [table for table, _ in calls]
        self.assertEqual(tables.count("order_intent_events"), len(intents))
        self.assertNotIn("paper_buy_events", tables)
        self.assertIn("protective_sell_events", tables)
        self.assertIn("gap_escape_events", tables)
        self.assertIn("profit_sell_events", tables)
        self.assertIn("event_risk_sell_events", tables)
        self.assertIn("options_order_events", tables)
        self.assertNotIn("order_ledger", tables)
        self.assertNotIn("execution_ledger", tables)
        self.assertTrue(all(values["order_submitted"] == 0 for _, values in calls))


if __name__ == "__main__":
    unittest.main()
