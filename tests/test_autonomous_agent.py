from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from scripts.run_autonomous_trading_agent import (
    build_research_tasks,
    build_quote_readiness,
    evaluate_lifecycle_state,
    failed_cycle,
    mode9_buy_freeze,
    should_run_strategy_now,
    streaming_report_payload,
    sync_canonical_pool_state,
    update_market_state,
)
from trading.market_data import Quote


class AutonomousAgentTests(unittest.TestCase):
    def lifecycle_for(
        self,
        *,
        health: dict | None = None,
        lock_state: str = "TRADE_LOCK",
        ready_for_orders: bool = True,
        ibkr_connected: bool = True,
        market_session: dict | None = None,
        quote_readiness: dict | None = None,
        errors: list[str] | None = None,
    ) -> dict:
        return evaluate_lifecycle_state(
            health=health or {"lock_state": "TRADE_LOCK"},
            lock_state=lock_state,
            ready_for_orders=ready_for_orders,
            ibkr_connected=ibkr_connected,
            market_session=market_session or {"session_state": "REGULAR", "expected_live_bid_ask": True},
            quote_readiness=quote_readiness
            or {
                "quotes_available": True,
                "quote_execution_ready": True,
                "fresh_bid_count": 1,
                "fresh_ask_count": 1,
                "blocked_reason": "",
            },
            errors=errors or [],
        )

    def test_mode9_market_closed_waits_without_execution(self) -> None:
        lifecycle = self.lifecycle_for(
            market_session={
                "session_state": "CLOSED",
                "expected_live_bid_ask": False,
                "blocked_reason": "market_closed_no_live_bid_ask_expected",
            }
        )

        self.assertEqual(lifecycle["lifecycle_state"], "MARKET_CLOSED_WAITING")
        self.assertFalse(lifecycle["execution_enabled"])

    def test_mode9_no_quotes_waits_without_execution(self) -> None:
        lifecycle = self.lifecycle_for(
            quote_readiness={
                "quotes_available": False,
                "quote_execution_ready": False,
                "fresh_bid_count": 0,
                "fresh_ask_count": 0,
                "blocked_reason": "waiting_for_quotes",
            }
        )

        self.assertEqual(lifecycle["lifecycle_state"], "WAITING_FOR_QUOTES")
        self.assertFalse(lifecycle["execution_enabled"])

    def test_mode9_stale_ask_waits_without_execution(self) -> None:
        lifecycle = self.lifecycle_for(
            quote_readiness={
                "quotes_available": True,
                "quote_execution_ready": False,
                "fresh_bid_count": 1,
                "fresh_ask_count": 0,
                "blocked_reason": "stale_or_missing_bid_ask",
            }
        )

        self.assertEqual(lifecycle["lifecycle_state"], "QUOTES_STALE_WAITING")
        self.assertFalse(lifecycle["execution_enabled"])

    def test_mode9_fresh_quotes_become_paper_ready(self) -> None:
        lifecycle = self.lifecycle_for()

        self.assertEqual(lifecycle["lifecycle_state"], "PAPER_READY")
        self.assertTrue(lifecycle["execution_enabled"])

    def test_mode9_disconnected_waits_without_execution(self) -> None:
        lifecycle = self.lifecycle_for(ibkr_connected=False)

        self.assertEqual(lifecycle["lifecycle_state"], "IBKR_DISCONNECTED")
        self.assertFalse(lifecycle["execution_enabled"])

    def test_mode9_ready_quotes_but_order_gate_blocked_by_risk(self) -> None:
        lifecycle = self.lifecycle_for(ready_for_orders=False)

        self.assertEqual(lifecycle["lifecycle_state"], "PAPER_BLOCKED_BY_RISK")
        self.assertFalse(lifecycle["execution_enabled"])

    def test_mode9_api_failure_is_recoverable_api_not_ready(self) -> None:
        import urllib.error

        cycle = failed_cycle(1, urllib.error.URLError("offline"), 1.0).as_dict()

        self.assertTrue(cycle["agent_running"])
        self.assertEqual(cycle["lifecycle_state"], "API_NOT_READY")
        self.assertFalse(cycle["execution_enabled"])
        self.assertFalse(cycle["order_submitted"])

    def test_quote_readiness_requires_fresh_bid_and_ask(self) -> None:
        now = datetime.now(timezone.utc)
        readiness = build_quote_readiness(
            quotes=[Quote("AAPL", 101.0, now, "test", bid=100.99, ask=None)],
            streaming_report=streaming_report_payload(None),
            max_age_ms=1000.0,
        )

        self.assertTrue(readiness["quotes_available"])
        self.assertFalse(readiness["quote_execution_ready"])
        self.assertEqual(readiness["fresh_bid_count"], 1)
        self.assertEqual(readiness["fresh_ask_count"], 0)

    def test_waiting_lifecycle_states_do_not_run_strategy(self) -> None:
        for state in [
            "API_NOT_READY",
            "IBKR_DISCONNECTED",
            "MARKET_CLOSED_WAITING",
            "WAITING_FOR_QUOTES",
            "QUOTES_STALE_WAITING",
            "ERROR_RECOVERABLE",
        ]:
            with self.subTest(state=state):
                self.assertFalse(
                    should_run_strategy_now(
                        disable_strategy=False,
                        lifecycle_state=state,
                        ready_for_orders=True,
                        lock_state="TRADE_LOCK",
                        strategy_every_cycles=1,
                        cycle=1,
                    )
                )

    def test_paper_ready_lifecycle_can_run_strategy_on_schedule(self) -> None:
        self.assertTrue(
            should_run_strategy_now(
                disable_strategy=False,
                lifecycle_state="PAPER_READY",
                ready_for_orders=True,
                lock_state="TRADE_LOCK",
                strategy_every_cycles=2,
                cycle=4,
            )
        )

    def test_update_market_state_ranks_intracycle_movers(self) -> None:
        state = {
            "AAPL": {"last": 100.0, "timestamp": 1.0},
            "MSFT": {"last": 200.0, "timestamp": 1.0},
        }
        now = datetime.now(timezone.utc)

        movers = update_market_state(
            state,
            [
                Quote("AAPL", 101.0, now, "test", bid=100.99, ask=101.01),
                Quote("MSFT", 196.0, now, "test", bid=195.9, ask=196.1),
            ],
        )

        self.assertEqual(movers[0]["symbol"], "MSFT")
        self.assertEqual(state["AAPL"]["last"], 101.0)

    def test_build_research_tasks_marks_allowed_symbols_high_priority(self) -> None:
        tasks = build_research_tasks(
            [
                {"symbol": "AAPL", "step_return": 0.01},
                {"symbol": "XYZ", "step_return": 0.02},
            ],
            module_allowed=["AAPL"],
        )

        self.assertEqual(tasks[0]["priority"], "high")
        self.assertEqual(tasks[1]["priority"], "watch")
        self.assertIn("SEC filings and earnings calendar", tasks[0]["requested_checks"])

    def test_streaming_report_is_empty_when_disabled(self) -> None:
        payload = streaming_report_payload(None)

        self.assertEqual(payload["streaming_symbols"], [])
        self.assertEqual(payload["streaming_quote_count"], 0)
        self.assertEqual(payload["streaming_stale_symbols"], [])
        self.assertEqual(payload["streaming_errors"], [])
        self.assertEqual(payload["streaming_quotes"], {})

    def test_mode9_buy_freeze_defaults_on(self) -> None:
        import os
        from unittest.mock import patch

        env = {key: value for key, value in os.environ.items() if key != "MODE9_BUY_FREEZE"}
        with patch.dict(os.environ, env, clear=True):
            self.assertTrue(mode9_buy_freeze())

    def test_canonical_pool_bridge_consumes_pool_manager_without_execution(self) -> None:
        now = datetime.now(timezone.utc)
        pool_manager = {
            "membership": {
                "records": [
                    {"symbol": "AAPL", "pool_name": "discovery_universe", "included": True, "source": "test"},
                    {"symbol": "AAPL", "pool_name": "tradable_universe", "included": True, "source": "test", "score": 80},
                    {"symbol": "AAPL", "pool_name": "stream_eligible_pool", "included": True, "source": "test", "score": 80},
                    {"symbol": "AAPL", "pool_name": "monitor_pool", "included": True, "source": "test", "score": 80},
                    {"symbol": "AAPL", "pool_name": "trade_pool", "included": True, "source": "test", "score": 80},
                ]
            },
            "audit": {"global_security_master_count": 1},
        }
        with tempfile.TemporaryDirectory() as tmp:
            report = sync_canonical_pool_state(
                pool_manager=pool_manager,
                market_session={"session_state": "REGULAR", "expected_live_bid_ask": True, "order_type_allowed": True},
                quote_readiness={"quotes_available": True, "quote_execution_ready": True},
                quotes=[Quote("AAPL", 100.05, now, "test", bid=100.0, ask=100.1)],
                streaming_report=streaming_report_payload(None),
                lifecycle={"lifecycle_state": "PAPER_READY", "execution_enabled": True},
                ready_for_orders=True,
                trace_id="test-cycle",
                db_path=Path(tmp) / "audit.sqlite3",
            )

        self.assertTrue(report["connected_to_mode9"])
        self.assertFalse(report["execution_active"])
        self.assertFalse(report["order_submitted"])
        self.assertEqual(report["runtime_symbol_count"], 1)
        self.assertIn("WATCH_POOL", report["canonical_layer_counts"])

    def test_canonical_pool_bridge_market_closed_waits_without_order(self) -> None:
        pool_manager = {
            "membership": {
                "records": [
                    {"symbol": "PFE", "pool_name": "discovery_universe", "included": True, "source": "test"},
                    {"symbol": "PFE", "pool_name": "tradable_universe", "included": True, "source": "test", "score": 70},
                    {"symbol": "PFE", "pool_name": "monitor_pool", "included": True, "source": "test", "score": 70},
                ]
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            report = sync_canonical_pool_state(
                pool_manager=pool_manager,
                market_session={"session_state": "WEEKEND", "expected_live_bid_ask": False, "blocked_reason": "market_weekend_no_live_bid_ask_expected"},
                quote_readiness={"quotes_available": False, "quote_execution_ready": False},
                quotes=[],
                streaming_report=streaming_report_payload(None),
                lifecycle={"lifecycle_state": "MARKET_CLOSED_WAITING", "execution_enabled": False},
                ready_for_orders=True,
                trace_id="test-cycle",
                db_path=Path(tmp) / "audit.sqlite3",
            )

        self.assertFalse(report["order_submitted"])
        self.assertIn("ELIGIBLE_UNIVERSE", report["canonical_layer_counts"])
        self.assertIn("MARKET_CLOSED_WAITING", report["blocked_reason_counts"])


if __name__ == "__main__":
    unittest.main()
