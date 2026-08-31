import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone

from research.paper_execution_gate import (
    CONFIRM_PHRASE,
    build_gate_report,
    execute_if_confirmed,
)


READY = {
    "status": "ready_for_manual_paper_review",
}

PLAN = {
    "candidates": [
        {
            "symbol": "AAPL",
            "validation_payload": {
                "symbol": "AAPL",
                "side": "BUY",
                "quantity": 1,
                "limit_price": 100.0,
                "idempotency_key": "validate-aapl-buy-1",
                "source": "paper_validation_plan",
            },
            "validation_result": {"approved": True},
        }
    ]
}


class PaperExecutionGateTests(unittest.TestCase):
    def test_build_gate_report_selects_approved_one_share_candidate(self) -> None:
        report = build_gate_report(READY, PLAN, readiness_path=Path("ready.json"), plan_path=Path("plan.json"))

        self.assertEqual(report.status, "ready_for_explicit_paper_submit")
        self.assertEqual(report.selected_symbol, "AAPL")
        self.assertEqual(report.selected_payload["quantity"], 1)

    def test_gate_blocks_without_ready_readiness(self) -> None:
        report = build_gate_report({"status": "validate_required"}, PLAN, readiness_path=Path("ready.json"), plan_path=Path("plan.json"))

        self.assertEqual(report.status, "blocked")

    def test_execute_requires_confirmation_phrase(self) -> None:
        report = build_gate_report(READY, PLAN, readiness_path=Path("ready.json"), plan_path=Path("plan.json"))

        result = execute_if_confirmed(
            report,
            confirm="wrong",
            trade_session_token="token",
            api_url="http://127.0.0.1:8787",
            api_key="key",
            timeout=1.0,
            request_json=lambda *args: {},
        )

        self.assertEqual(result.status, "blocked")
        self.assertIn(CONFIRM_PHRASE, result.reason)

    def test_execute_posts_paper_limit_after_health_passes(self) -> None:
        calls = []

        def fake_request(method, path, payload, api_url, api_key, timeout):
            calls.append((method, path, payload))
            if path == "/health":
                return {
                    "lock_state": "TRADE_LOCK",
                    "paper_transmit_enabled": True,
                    "kill_switch_enabled": False,
                    "tws": {"ready_for_orders": True},
                }
            return {"approved": True, "status": "PAPER_LIMIT_SUBMITTED"}

        report = build_gate_report(READY, PLAN, readiness_path=Path("ready.json"), plan_path=Path("plan.json"))
        result = execute_if_confirmed(
            report,
            confirm=CONFIRM_PHRASE,
            trade_session_token="token",
            api_url="http://127.0.0.1:8787",
            api_key="key",
            timeout=1.0,
            request_json=fake_request,
        )

        self.assertEqual(result.status, "submitted")
        self.assertEqual(calls[0][1], "/health")
        self.assertEqual(calls[1][1], "/v1/orders/paper/limit")
        self.assertEqual(calls[1][2]["trade_session_token"], "token")

    def test_execute_accepts_matching_pre_submit_review(self) -> None:
        calls = []

        def fake_request(method, path, payload, api_url, api_key, timeout):
            calls.append(path)
            if path == "/health":
                return {
                    "lock_state": "TRADE_LOCK",
                    "paper_transmit_enabled": True,
                    "kill_switch_enabled": False,
                    "tws": {"ready_for_orders": True},
                }
            return {"approved": True}

        report = build_gate_report(READY, PLAN, readiness_path=Path("ready.json"), plan_path=Path("plan.json"))
        result = execute_if_confirmed(
            report,
            confirm=CONFIRM_PHRASE,
            trade_session_token="token",
            api_url="http://127.0.0.1:8787",
            api_key="key",
            timeout=1.0,
            pre_submit_review={
                "status": "ready_for_operator_confirmation",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "selected_payload": dict(report.selected_payload),
            },
            request_json=fake_request,
        )

        self.assertEqual(result.status, "submitted")
        self.assertEqual(calls, ["/health", "/v1/orders/paper/limit"])

    def test_execute_blocks_stale_pre_submit_review(self) -> None:
        report = build_gate_report(READY, PLAN, readiness_path=Path("ready.json"), plan_path=Path("plan.json"))
        result = execute_if_confirmed(
            report,
            confirm=CONFIRM_PHRASE,
            trade_session_token="token",
            api_url="http://127.0.0.1:8787",
            api_key="key",
            timeout=1.0,
            pre_submit_review={
                "status": "ready_for_operator_confirmation",
                "created_at": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
                "selected_payload": dict(report.selected_payload),
            },
            max_review_age_seconds=60.0,
            request_json=lambda *args: {},
        )

        self.assertEqual(result.status, "blocked")
        self.assertIn("stale", result.reason)

    def test_execute_blocks_pre_submit_review_payload_mismatch(self) -> None:
        report = build_gate_report(READY, PLAN, readiness_path=Path("ready.json"), plan_path=Path("plan.json"))
        payload = dict(report.selected_payload)
        payload["limit_price"] = 101.0
        result = execute_if_confirmed(
            report,
            confirm=CONFIRM_PHRASE,
            trade_session_token="token",
            api_url="http://127.0.0.1:8787",
            api_key="key",
            timeout=1.0,
            pre_submit_review={
                "status": "ready_for_operator_confirmation",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "selected_payload": payload,
            },
            request_json=lambda *args: {},
        )

        self.assertEqual(result.status, "blocked")
        self.assertIn("mismatch", result.reason)


if __name__ == "__main__":
    unittest.main()
