import sqlite3
import tempfile
import unittest
from pathlib import Path

from trading.audit_writer import AuditWriter
from trading.buy_decision_engine import build_buy_intent, submit_order as buy_submit_order
from trading.cycle_snapshot import create_cycle_snapshot
from trading.order_intent_router import route_synchronized_intents
from trading.position_lifecycle_manager import PositionLifecycleManager
from trading.realtime_account_state_bus import RealtimeAccountStateBus
from trading.realtime_account_sync import run_realtime_account_sync
from trading.sell_decision_engine import build_sell_intent, submit_order as sell_submit_order
from trading.sqlite_event_store import SQLiteEventStore
from trading.state_freshness_policy import FreshnessThresholds, evaluate_freshness
from trading.strategy_signals import create_strategy_signal, submit_order as strategy_submit_order


class RealtimeAccountSyncTests(unittest.TestCase):
    def test_realtime_bus_accepts_state_events(self) -> None:
        writer = AuditWriter()
        bus = RealtimeAccountStateBus(audit_writer=writer)

        bus.update("quote", {"symbol": "AAPL", "bid": 100, "ask": 100.02, "last": 100.01}, source_module="test")
        bus.update("account", {"net_liquidation": 100000}, source_module="test")
        bus.update("position", {"symbol": "AAPL", "position_qty": 1}, source_module="test")
        bus.update("pnl", {"daily_pnl": 1.2}, source_module="test")
        bus.update("open_order", {"symbol": "AAPL", "open_orders": []}, source_module="test")
        bus.update("execution", {"symbol": "AAPL", "fills": []}, source_module="test")

        self.assertEqual(bus.state_version, 6)
        self.assertEqual(bus.latest_quote_state.payload["symbol"], "AAPL")

    def test_cycle_snapshot_captures_latest_state_versions(self) -> None:
        writer = AuditWriter()
        bus = RealtimeAccountStateBus(audit_writer=writer)
        bus.update("account", {"account": "x"}, source_module="test")
        bus.update("quote", {"symbol": "AAPL", "bid": 1, "ask": 1.01}, source_module="test")

        snapshot = create_cycle_snapshot(bus, cycle_id="cycle", trigger_event_id="trigger", audit_writer=writer)

        self.assertEqual(snapshot.state_version_min, 1)
        self.assertEqual(snapshot.state_version_max, 2)
        self.assertTrue(snapshot.immutable)

    def test_buy_and_sell_decisions_share_same_snapshot_id(self) -> None:
        writer = AuditWriter()
        bus = RealtimeAccountStateBus(audit_writer=writer)
        bus.update("account", {"account": "x"}, source_module="test")
        bus.update("quote", {"symbol": "NVDA", "bid": 1, "ask": 1.01}, source_module="test")
        snapshot = create_cycle_snapshot(bus, cycle_id="sync", trigger_event_id="trigger", audit_writer=writer)
        buy_signal = create_strategy_signal(cycle_id="sync", snapshot_id=snapshot.snapshot_id, symbol="NVDA", direction="BUY_BIAS", source_reason="test", audit_writer=writer)
        sell_signal = create_strategy_signal(cycle_id="sync", snapshot_id=snapshot.snapshot_id, symbol="PFE", direction="SELL_REVIEW", source_reason="test", audit_writer=writer)

        buy = build_buy_intent(buy_signal, snapshot)
        sell = build_sell_intent(sell_signal, snapshot, position_qty_before=8)

        self.assertEqual(buy.snapshot_id, sell.snapshot_id)
        self.assertEqual(buy.state_version_max, sell.state_version_max)

    def test_high_priority_sell_blocks_same_symbol_buy(self) -> None:
        writer = AuditWriter()
        bus = RealtimeAccountStateBus(audit_writer=writer)
        bus.update("account", {"account": "x"}, source_module="test")
        snapshot = create_cycle_snapshot(bus, cycle_id="conflict", trigger_event_id="trigger", audit_writer=writer)
        signal = create_strategy_signal(cycle_id="conflict", snapshot_id=snapshot.snapshot_id, symbol="PFE", direction="BUY_BIAS", source_reason="test", audit_writer=writer)

        buy = build_buy_intent(signal, snapshot)
        sell = build_sell_intent(signal, snapshot, intent_type="GAP_ESCAPE_SELL_LMT", position_qty_before=8)
        report = route_synchronized_intents([buy, sell], audit_writer=writer)

        self.assertEqual(len(report["conflicts"]), 1)
        self.assertEqual(report["conflicts"][0]["decision"], "block_buy")

    def test_freshness_blocks_stale_quote_pnl_and_position(self) -> None:
        writer = AuditWriter()
        bus = RealtimeAccountStateBus(audit_writer=writer)
        quote = bus.update("quote", {"symbol": "AAPL"}, source_module="test")
        pnl = bus.update("pnl", {"daily_pnl": 1}, source_module="test")
        position = bus.update("position", {"symbol": "AAPL", "position_qty": 1}, source_module="test")
        object.__setattr__(quote, "freshness_age_sec", 10.0)
        object.__setattr__(pnl, "freshness_age_sec", 10.0)
        object.__setattr__(position, "freshness_age_sec", 10.0)

        result = evaluate_freshness(bus, side="SELL", mode="IBKR_PAPER_READINESS", thresholds=FreshnessThresholds(quote_max_age_sec=1, pnl_max_age_sec=1, position_max_age_sec=1))

        self.assertIn("stale_quote", result["blocked_reasons"])
        self.assertIn("stale_pnl", result["blocked_reasons"])
        self.assertIn("stale_position", result["blocked_reasons"])
        self.assertIn("stale_bid", result["blocked_reasons"])

    def test_audit_writer_is_single_writer_and_wal_enabled_append_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteEventStore(Path(directory) / "audit.sqlite3")
            writer = AuditWriter(store)
            writer.submit_event_store(event_id="e1", source_module="test", event_type="x")
            writer.submit_event_store(event_id="e2", source_module="test", event_type="x")
            written = writer.flush()
            with sqlite3.connect(store.db_path) as con:
                count = con.execute("select count(*) from event_store").fetchone()[0]
            journal_mode = store.journal_mode()

        self.assertEqual(written, 2)
        self.assertEqual(count, 2)
        self.assertEqual(journal_mode, "wal")

    def test_buy_event_has_pending_protection_fields(self) -> None:
        writer = AuditWriter()
        bus = RealtimeAccountStateBus(audit_writer=writer)
        bus.update("account", {"account": "x"}, source_module="test")
        snapshot = create_cycle_snapshot(bus, cycle_id="protection", trigger_event_id="trigger", audit_writer=writer)
        signal = create_strategy_signal(cycle_id="protection", snapshot_id=snapshot.snapshot_id, symbol="NVDA", direction="BUY_BIAS", source_reason="test", audit_writer=writer)
        buy = build_buy_intent(signal, snapshot)

        self.assertTrue(buy.protection_plan_required)
        self.assertEqual(buy.protection_plan_status, "PENDING")

    def test_position_lifecycle_state_is_written(self) -> None:
        manager = PositionLifecycleManager()
        state = manager.transition(symbol="NVDA", to_state="PROTECTION_PENDING", intent_id="intent")
        report = manager.write_report()

        self.assertEqual(state.current_state, "PROTECTION_PENDING")
        self.assertEqual(state.protection_plan_status, "PENDING")
        self.assertEqual(report["states"][0]["current_state"], "PROTECTION_PENDING")

    def test_strategies_and_engines_cannot_submit_orders(self) -> None:
        with self.assertRaises(RuntimeError):
            strategy_submit_order()
        with self.assertRaises(RuntimeError):
            buy_submit_order()
        with self.assertRaises(RuntimeError):
            sell_submit_order()

    def test_end_to_end_reports_no_real_order_or_snapshot_risk(self) -> None:
        result = run_realtime_account_sync("unit-realtime")
        sync = result["realtime_account_sync"]

        self.assertTrue(sync["account_state_event_driven"])
        self.assertFalse(sync["fixed_30_second_cycle_used_for_execution"])
        self.assertEqual(sync["ibkr_paper_orders_submitted"], 0)
        self.assertEqual(sync["live_orders_submitted"], 0)
        self.assertFalse(sync["market_order_used"])
        self.assertFalse(sync["paid_snapshot_used"])
        self.assertFalse(sync["regulatory_snapshot_used"])


if __name__ == "__main__":
    unittest.main()
