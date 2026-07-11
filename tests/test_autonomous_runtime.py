import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from trading.autonomous_runtime import AutonomousPaperRuntime, AutonomousRuntimeConfig


ET = ZoneInfo("America/New_York")


class FakeScanner:
    def __init__(self, events):
        self.events = events

    def scan_once(self):
        return {
            "requested_symbols": ["AAPL"],
            "returned_symbols": ["AAPL"],
            "events": self.events,
        }


class AutonomousRuntimeTests(unittest.TestCase):
    def test_kill_switch_blocks_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _runtime(tmp, config=AutonomousRuntimeConfig(kill_switch=True, status_path=Path(tmp) / "status.json", events_path=Path(tmp) / "events.jsonl"))

            report = runtime.run_once()

        self.assertEqual(report.state, "KILL_SWITCH")

    def test_tws_health_failure_pauses_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _runtime(tmp, health={"status": "ok", "mode": "PAPER", "lock_state": "DEV_LOCK"})

            report = runtime.run_once()

        self.assertEqual(report.state, "PAUSED")

    def test_runtime_submits_session_approved_bracket_order(self) -> None:
        submissions = []
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _runtime(
                tmp,
                events=[_event()],
                submitter=lambda proposal: submissions.append(proposal) or {"approved": True, "status": "PAPER_SUBMITTED"},
            )

            report = runtime.run_once()

        self.assertEqual(report.submitted_count, 1)
        self.assertEqual(submissions[0].symbol, "AAPL")
        self.assertIsNotNone(submissions[0].stop_price)

    def test_runtime_blocks_event_without_protective_stop(self) -> None:
        event = _event()
        event["proposal"].pop("stop_price")
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _runtime(tmp, events=[event])

            report = runtime.run_once()

        self.assertEqual(report.submitted_count, 0)
        self.assertEqual(report.events[0]["runtime_action"], "no_proposal")

    def test_live_order_remains_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _runtime(tmp, config=AutonomousRuntimeConfig(paper_only=False, status_path=Path(tmp) / "status.json", events_path=Path(tmp) / "events.jsonl"))

            report = runtime.run_once()

        self.assertEqual(report.state, "KILL_SWITCH")


def _runtime(tmp, *, events=None, health=None, submitter=None, config=None):
    return AutonomousPaperRuntime(
        scanner=FakeScanner(events or []),
        config=config or AutonomousRuntimeConfig(status_path=Path(tmp) / "status.json", events_path=Path(tmp) / "events.jsonl"),
        health_provider=lambda: health or _ready_health(),
        open_orders_provider=lambda: [],
        submitter=submitter or (lambda proposal: {"approved": True}),
        clock=lambda: datetime(2026, 7, 8, 10, 0, tzinfo=ET),
    )


def _ready_health():
    return {
        "status": "ok",
        "mode": "PAPER",
        "lock_state": "TRADE_LOCK",
        "paper_transmit_enabled": True,
        "kill_switch_enabled": False,
        "tws": {"ready_for_orders": True},
    }


def _event():
    return {
        "symbol": "AAPL",
        "price": 100.0,
        "bid": 99.99,
        "ask": 100.01,
        "quote_source": "test",
        "strategy_name": "tactical_long",
        "proposal": {
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": 1,
            "limit_price": 100.01,
            "stop_price": 99.0,
            "idempotency_key": "runtime-aapl-0001",
        },
    }


if __name__ == "__main__":
    unittest.main()
