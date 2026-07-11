import sqlite3
import tempfile
import unittest
from pathlib import Path

from trading.pool_state import PoolStateManager


NOW = "2026-07-10T14:30:00+00:00"
FRESH_QUOTE = {"bid": 100.0, "ask": 100.1, "last": 100.05, "timestamp": NOW}


class PoolStateTests(unittest.TestCase):
    def manager(self) -> PoolStateManager:
        self.tmp = tempfile.TemporaryDirectory()
        return PoolStateManager(db_path=Path(self.tmp.name) / "audit.sqlite3", now=NOW)

    def add_ready_watch(self, mgr: PoolStateManager, symbol: str = "AAPL"):
        mgr.upsert_master(symbol=symbol, source="fixture")
        mgr.evaluate_eligibility(symbol, contract_resolved=True, price=100, average_volume=2_000_000)
        mgr.nominate_scan(symbol, strategy="value_pullback", score=80, reason="coarse setup", data_timestamp=NOW)
        return mgr.promote_to_watch(symbol, strategy="value_pullback", quote=FRESH_QUOTE, entry_reason="near trigger", score=82)

    def test_normal_l1_to_l6_promotion(self) -> None:
        mgr = self.manager()
        self.add_ready_watch(mgr)
        mgr.evaluate_signal(
            "AAPL",
            signal={"valid": True, "timestamp": NOW, "score": 90, "strategy_confirmed": True},
            market_session={"expected_live_bid_ask": True, "order_type_allowed": True},
            risk={"approved": True},
            execution={"paper_account_confirmed": True, "live_trading_enabled": False, "contract_resolved": True},
        )
        state = mgr.enter_execution_pool("AAPL", order_id="1", intent_id="intent-1")

        self.assertEqual(state.current_layer, "PAPER_EXECUTION_POSITION_POOL")
        self.assertEqual([t.to_layer for t in state.transition_history], [
            "MASTER_UNIVERSE",
            "ELIGIBLE_UNIVERSE",
            "SCAN_POOL",
            "WATCH_POOL",
            "SIGNAL_EXECUTION_READY_POOL",
            "PAPER_EXECUTION_POSITION_POOL",
        ])

    def test_ineligible_symbol_remains_outside_l2(self) -> None:
        mgr = self.manager()
        mgr.upsert_master(symbol="BAD", source="fixture")
        state = mgr.evaluate_eligibility("BAD", contract_resolved=False)

        self.assertEqual(state.current_layer, "MASTER_UNIVERSE")
        self.assertIn("CONTRACT_NOT_RESOLVED", state.eligibility["failed_checks"])

    def test_stale_ask_blocks_l5_to_l6(self) -> None:
        mgr = self.manager()
        mgr.added = self.add_ready_watch(mgr)
        stale = {"bid": 100.0, "ask": 100.1, "last": 100.0, "timestamp": "2026-07-10T14:00:00+00:00"}
        state = mgr.promote_to_watch("AAPL", strategy="value_pullback", quote=stale, entry_reason="near trigger", score=90)

        self.assertEqual(state.current_layer, "ELIGIBLE_UNIVERSE")
        self.assertEqual(state.transition_history[-1].reason_code, "STALE_ASK")

    def test_market_closed_blocks_unsupported_execution(self) -> None:
        mgr = self.manager()
        self.add_ready_watch(mgr)
        state = mgr.evaluate_signal(
            "AAPL",
            signal={"valid": True, "timestamp": NOW, "score": 90, "strategy_confirmed": True},
            market_session={"expected_live_bid_ask": False, "order_type_allowed": False},
            risk={"approved": True},
            execution={"paper_account_confirmed": True, "live_trading_enabled": False, "contract_resolved": True},
        )

        self.assertEqual(state.current_layer, "WATCH_POOL")
        self.assertIn("MARKET_CLOSED", state.transition_history[-1].explanation)

    def test_spread_widening_demotes_watch_pool_symbol(self) -> None:
        mgr = self.manager()
        self.add_ready_watch(mgr)
        state = mgr.promote_to_watch("AAPL", strategy="value_pullback", quote={"bid": 90, "ask": 110, "timestamp": NOW}, entry_reason="still watching", score=70)

        self.assertEqual(state.current_layer, "ELIGIBLE_UNIVERSE")
        self.assertEqual(state.transition_history[-1].reason_code, "SPREAD_TOO_WIDE")

    def test_expired_signal_is_removed(self) -> None:
        mgr = self.manager()
        self.add_ready_watch(mgr)
        state = mgr.evaluate_signal(
            "AAPL",
            signal={"valid": True, "timestamp": "2026-07-10T14:00:00+00:00", "score": 90, "strategy_confirmed": True},
            market_session={"expected_live_bid_ask": True, "order_type_allowed": True},
            risk={"approved": True},
            execution={"paper_account_confirmed": True, "live_trading_enabled": False, "contract_resolved": True},
            max_signal_age_sec=60,
        )

        self.assertEqual(state.current_layer, "WATCH_POOL")
        self.assertIn("SIGNAL_EXPIRED", state.transition_history[-1].explanation)

    def test_expired_news_event_cannot_authorize_trade(self) -> None:
        mgr = self.manager()
        self.add_ready_watch(mgr)
        state = mgr.evaluate_signal(
            "AAPL",
            signal={"valid": True, "timestamp": NOW, "score": 90, "source": "news"},
            market_session={"expected_live_bid_ask": True, "order_type_allowed": True},
            risk={"approved": True},
            execution={"paper_account_confirmed": True, "live_trading_enabled": False, "contract_resolved": True},
            news_events=[{"event_id": "n1", "symbol": "AAPL", "expiration_time": "2026-07-10T13:00:00+00:00"}],
        )

        self.assertEqual(state.current_layer, "WATCH_POOL")
        self.assertIn("NEWS_EVENT_CANNOT_AUTHORIZE_TRADE", state.transition_history[-1].explanation)

    def test_duplicate_order_is_blocked(self) -> None:
        mgr = self.manager()
        self.add_ready_watch(mgr)
        mgr.evaluate_signal(
            "AAPL",
            signal={"valid": True, "timestamp": NOW, "score": 90, "strategy_confirmed": True},
            market_session={"expected_live_bid_ask": True, "order_type_allowed": True},
            risk={"approved": True},
            execution={"paper_account_confirmed": True, "live_trading_enabled": False, "contract_resolved": True},
        )
        mgr.enter_execution_pool("AAPL", order_id="1", intent_id="intent-1")
        state = mgr.enter_execution_pool("AAPL", order_id="2", intent_id="intent-2")

        self.assertEqual(state.transition_history[-1].reason_code, "DUPLICATE_ORDER")

    def test_live_account_or_unconfirmed_account_is_blocked(self) -> None:
        mgr = self.manager()
        self.add_ready_watch(mgr)
        state = mgr.evaluate_signal(
            "AAPL",
            signal={"valid": True, "timestamp": NOW, "score": 90, "strategy_confirmed": True},
            market_session={"expected_live_bid_ask": True, "order_type_allowed": True},
            risk={"approved": True},
            execution={"paper_account_confirmed": False, "live_trading_enabled": True, "contract_resolved": True},
        )

        self.assertEqual(state.current_layer, "WATCH_POOL")
        self.assertIn("LIVE_TRADING_DISABLED", state.transition_history[-1].explanation)
        self.assertIn("PAPER_ACCOUNT_NOT_CONFIRMED", state.transition_history[-1].explanation)

    def test_restart_does_not_duplicate_order(self) -> None:
        mgr = self.manager()
        db = mgr.db_path
        self.add_ready_watch(mgr)
        mgr.evaluate_signal(
            "AAPL",
            signal={"valid": True, "timestamp": NOW, "score": 90, "strategy_confirmed": True},
            market_session={"expected_live_bid_ask": True, "order_type_allowed": True},
            risk={"approved": True},
            execution={"paper_account_confirmed": True, "live_trading_enabled": False, "contract_resolved": True},
        )
        mgr.enter_execution_pool("AAPL", order_id="1", intent_id="intent-1")

        restored = PoolStateManager(db_path=db, now=NOW)
        restored.load()
        state = restored.enter_execution_pool("AAPL", order_id="2", intent_id="intent-2")

        self.assertEqual(state.transition_history[-1].reason_code, "DUPLICATE_ORDER")

    def test_ibkr_rejection_moves_candidate_to_correct_state(self) -> None:
        mgr = self.manager()
        self.add_ready_watch(mgr)
        mgr.evaluate_signal(
            "AAPL",
            signal={"valid": True, "timestamp": NOW, "score": 90, "strategy_confirmed": True},
            market_session={"expected_live_bid_ask": True, "order_type_allowed": True},
            risk={"approved": True},
            execution={"paper_account_confirmed": True, "live_trading_enabled": False, "contract_resolved": True},
        )
        mgr.enter_execution_pool("AAPL", order_id="1", intent_id="intent-1")
        state = mgr.apply_order_callback("AAPL", callback_status="REJECTED", reason="IBKR rejected")

        self.assertEqual(state.execution_state["status"], "REJECTED")
        self.assertEqual(state.transition_history[-1].reason_code, "IBKR_REJECTED")

    def test_partial_fill_is_distinguished_from_full_fill(self) -> None:
        mgr = self.manager()
        self.add_ready_watch(mgr)
        mgr.evaluate_signal(
            "AAPL",
            signal={"valid": True, "timestamp": NOW, "score": 90, "strategy_confirmed": True},
            market_session={"expected_live_bid_ask": True, "order_type_allowed": True},
            risk={"approved": True},
            execution={"paper_account_confirmed": True, "live_trading_enabled": False, "contract_resolved": True},
        )
        mgr.enter_execution_pool("AAPL", order_id="1", intent_id="intent-1")
        partial = mgr.apply_order_callback("AAPL", callback_status="PARTIALLY_FILLED", filled_quantity=1, remaining_quantity=2)
        filled = mgr.apply_order_callback("AAPL", callback_status="FILLED", filled_quantity=3, remaining_quantity=0)

        self.assertEqual(partial.position_state["position_status"], "PARTIAL")
        self.assertEqual(filled.position_state["position_status"], "OPEN")

    def test_multiple_strategies_assess_one_symbol_without_corrupting_state(self) -> None:
        mgr = self.manager()
        mgr.upsert_master(symbol="AAPL", source="fixture")
        mgr.evaluate_eligibility("AAPL", contract_resolved=True, price=100, average_volume=2_000_000)
        mgr.nominate_scan("AAPL", strategy="value", score=70, reason="cheap")
        state = mgr.nominate_scan("AAPL", strategy="momentum", score=80, reason="trend")

        self.assertEqual(state.symbol, "AAPL")
        self.assertEqual(set(state.strategy_assessments), {"value", "momentum"})

    def test_out_of_order_callbacks_do_not_move_state_backward(self) -> None:
        mgr = self.manager()
        self.add_ready_watch(mgr)
        mgr.evaluate_signal(
            "AAPL",
            signal={"valid": True, "timestamp": NOW, "score": 90, "strategy_confirmed": True},
            market_session={"expected_live_bid_ask": True, "order_type_allowed": True},
            risk={"approved": True},
            execution={"paper_account_confirmed": True, "live_trading_enabled": False, "contract_resolved": True},
        )
        mgr.enter_execution_pool("AAPL", order_id="1", intent_id="intent-1")
        mgr.apply_order_callback("AAPL", callback_status="FILLED", filled_quantity=3)
        state = mgr.apply_order_callback("AAPL", callback_status="SUBMITTED")

        self.assertEqual(state.execution_state["status"], "FILLED")
        self.assertEqual(state.transition_history[-1].reason_code, "OUT_OF_ORDER_CALLBACK_IGNORED")

    def test_promotion_and_demotion_reasons_are_persisted(self) -> None:
        mgr = self.manager()
        db = mgr.db_path
        self.add_ready_watch(mgr)
        mgr.promote_to_watch("AAPL", strategy="value_pullback", quote={"bid": 90, "ask": 110, "timestamp": NOW}, entry_reason="still watching", score=70)

        with sqlite3.connect(db) as con:
            reasons = [row[0] for row in con.execute("select reason_code from canonical_pool_transition_events")]

        self.assertIn("WATCH_PROMOTED", reasons)
        self.assertIn("SPREAD_TOO_WIDE", reasons)


if __name__ == "__main__":
    unittest.main()
