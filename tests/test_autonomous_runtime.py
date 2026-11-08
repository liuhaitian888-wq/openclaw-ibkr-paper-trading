import tempfile
import unittest
from datetime import datetime, timezone, timedelta
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
    def test_missing_stale_future_naive_or_crossed_quote_never_submits(self):
        for changes in [
            {'quote_timestamp': None}, {'quote_timestamp': 'bad'},
            {'quote_timestamp': datetime.now().isoformat()},
            {'quote_timestamp': (datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()},
            {'quote_timestamp': (datetime.now(timezone.utc)+timedelta(minutes=1)).isoformat()},
            {'bid': None}, {'ask': float('nan')}, {'bid': 101, 'ask': 100},
        ]:
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as tmp:
                submitted=[]
                runtime=_runtime(tmp,events=[{**_event(), **changes}],submitter=lambda p: submitted.append(p) or {'approved': True})
                report=runtime.run_once()
                self.assertEqual(submitted, [])
                self.assertEqual(report.submitted_count, 0)

    def test_uncertain_or_exception_submission_stops_cycle_without_retry(self):
        outcomes = [
            {'approved': True, 'status': 'PAPER_PENDING_CONFIRMATION'},
            {'approved': False, 'status': 'UNKNOWN'},
            {'approved': True, 'status': 'UNKNOWN'},
            {},
            RuntimeError('transport outcome unknown'),
        ]
        for outcome in outcomes:
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as tmp:
                calls=[]
                def submit(p):
                    calls.append(p)
                    if isinstance(outcome, Exception): raise outcome
                    return outcome
                runtime=_runtime(tmp,events=[_event(),_event()],submitter=submit)
                report=runtime.run_once()
                self.assertEqual(len(calls),1)
                self.assertEqual(report.state,'RECONCILIATION_REQUIRED')
                self.assertEqual(report.events[0]['runtime_action'],'submission_uncertain')
                # A second cycle must remain blocked, even when health stays green.
                runtime.run_once()
                self.assertEqual(len(calls),1)
                restarted=_runtime(tmp,events=[_event()],submitter=submit)
                after_restart=restarted.run_once()
                self.assertEqual(len(calls),1)
                self.assertEqual(after_restart.events[0]['proposal']['idempotency_key'],'runtime-aapl-0001')

    def test_confirmed_submission_requires_new_snapshot_before_next_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls=[]
            runtime=_runtime(tmp,events=[_event(),_event()],submitter=lambda p: calls.append(p) or {'approved':True,'status':'PAPER_SUBMITTED'})
            runtime.run_once()
            self.assertEqual(len(calls),1)

    def test_started_intent_is_durable_before_submitter_is_called(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            def submit(p):
                data=json.loads((Path(tmp)/'status.json').read_text())
                self.assertEqual(data['state'],'RECONCILIATION_REQUIRED')
                self.assertEqual(data['events'][0]['proposal']['idempotency_key'],p.idempotency_key)
                raise SystemExit('simulated process exit')
            runtime=_runtime(tmp,events=[_event()],submitter=submit)
            with self.assertRaises(SystemExit): runtime.run_once()
            calls=[]
            _runtime(tmp,events=[_event()],submitter=lambda p: calls.append(p)).run_once()
            self.assertEqual(calls,[])

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
        "quote_timestamp": datetime.now(timezone.utc).isoformat(),
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
