import unittest
from datetime import datetime, timedelta, timezone

from trading.audit_writer import AuditWriter
from trading.data_buses import build_data_bus_architecture_report
from trading.ibkr_callback_bridge import IbkrCallbackBridge, run_ibkr_callback_dry_run
from trading.ibkr_callback_wiring_audit import build_ibkr_callback_wiring_audit
from trading.realtime_account_state_bus import RealtimeAccountStateBus
from trading.state_bootstrap_manager import StateBootstrapManager
from trading.state_timestamp_reconciler import TimestampReconciler
from trading.subscription_health import build_subscription_health_report


class IbkrCallbackBridgeTests(unittest.TestCase):
    def test_data_bus_architecture_has_four_logical_buses(self) -> None:
        report = build_data_bus_architecture_report()

        self.assertEqual(report["logical_bus_count"], 4)
        self.assertTrue(report["buses_logically_separated"])
        self.assertTrue(report["decision_snapshots_reference_all_buses"])

    def test_bootstrap_loads_cache_then_waits_for_real_ibkr(self) -> None:
        writer = AuditWriter()
        bus = RealtimeAccountStateBus(audit_writer=writer)
        report = StateBootstrapManager(bus, audit_writer=writer).bootstrap(start_real_ibkr_subscriptions=True)

        self.assertTrue(report["local_cache_loaded"])
        self.assertEqual(report["bus_status"], "WAITING_FOR_REAL_IBKR")
        self.assertTrue(report["real_ibkr_subscriptions_started_after_cache"])

    def test_real_ibkr_callback_writes_to_bus_and_replaces_cache(self) -> None:
        bridge = IbkrCallbackBridge(symbols_by_req_id={1: "AAPL"})
        StateBootstrapManager(bridge.account_bus, audit_writer=bridge.audit_writer).bootstrap(start_real_ibkr_subscriptions=True)
        before = bridge.account_bus.state_version

        bridge.tickPrice(1, 2, 101.25, object())

        self.assertGreater(bridge.account_bus.state_version, before)
        self.assertEqual(bridge.account_bus.latest_quote_state.payload["source_type"], "REAL_IBKR")
        self.assertEqual(bridge.callback_counts["tickPrice"], 1)

    def test_older_real_ibkr_event_is_stored_but_does_not_overwrite_newer(self) -> None:
        reconciler = TimestampReconciler()
        newer = datetime.now(timezone.utc)
        older = newer - timedelta(seconds=10)

        first, accepted_first = reconciler.reconcile(field_name="ask", symbol="AAPL", value=101, source_type="REAL_IBKR", source_timestamp=newer.isoformat())
        second, accepted_second = reconciler.reconcile(field_name="ask", symbol="AAPL", value=99, source_type="REAL_IBKR", source_timestamp=older.isoformat())

        self.assertTrue(accepted_first)
        self.assertFalse(accepted_second)
        self.assertEqual(reconciler.latest[("AAPL", "ask")].value, 101)
        self.assertEqual(len(reconciler.events), 2)

    def test_stale_field_remains_subscribed_and_new_event_returns_fresh(self) -> None:
        reconciler = TimestampReconciler()
        old = datetime.now(timezone.utc) - timedelta(seconds=10)
        stale, _ = reconciler.reconcile(field_name="ask", symbol="AAPL", value=100, source_type="REAL_IBKR", source_timestamp=old.isoformat(), stale_threshold_sec=1)
        fresh, _ = reconciler.reconcile(field_name="ask", symbol="AAPL", value=101, source_type="REAL_IBKR", source_timestamp=datetime.now(timezone.utc).isoformat(), stale_threshold_sec=1)
        subscription = build_subscription_health_report()

        self.assertEqual(stale.freshness_status, "STALE_BUT_LISTENING")
        self.assertEqual(fresh.freshness_status, "FRESH")
        self.assertFalse(subscription["stale_did_disable_subscription"])
        self.assertTrue(subscription["auto_return_to_fresh_on_new_callback"])

    def test_ask_freshness_independent_from_other_domains(self) -> None:
        reconciler = TimestampReconciler()
        old = datetime.now(timezone.utc) - timedelta(seconds=10)
        ask, _ = reconciler.reconcile(field_name="ask", symbol="AAPL", value=100, source_type="REAL_IBKR", source_timestamp=old.isoformat(), stale_threshold_sec=1)
        bid, _ = reconciler.reconcile(field_name="bid", symbol="AAPL", value=99, source_type="REAL_IBKR", source_timestamp=datetime.now(timezone.utc).isoformat(), stale_threshold_sec=1)
        pnl, _ = reconciler.reconcile(field_name="pnl", symbol="AAPL", value=1.2, source_type="REAL_IBKR", source_timestamp=datetime.now(timezone.utc).isoformat(), stale_threshold_sec=1)

        self.assertEqual(ask.freshness_status, "STALE_BUT_LISTENING")
        self.assertEqual(bid.freshness_status, "FRESH")
        self.assertEqual(pnl.freshness_status, "FRESH")

    def test_dry_run_uses_no_orders_or_snapshots(self) -> None:
        report = run_ibkr_callback_dry_run(duration_seconds=0, symbols=["AAPL"])

        self.assertFalse(report["snapshot_request_used"])
        self.assertFalse(report["regulatory_snapshot_used"])
        self.assertFalse(report["paid_snapshot_used"])
        self.assertEqual(report["orders_submitted"], 0)
        self.assertEqual(report["orders_cancelled"], 0)

    def test_wiring_audit_reports_bridge_separately_from_real_events(self) -> None:
        report = build_ibkr_callback_wiring_audit()
        tick_price = next(row for row in report["callback_wiring"] if row["callback_name"] == "tickPrice")

        self.assertTrue(tick_price["wired_to_realtime_bus"])
        self.assertIn(tick_price["last_event_source"], {"REAL_IBKR", "NONE"})
        self.assertIn("REAL_IBKR", report["last_event_source_categories"])


if __name__ == "__main__":
    unittest.main()
