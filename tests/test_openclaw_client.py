import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from openclaw.openclaw_trading_client import (
    PENDING_CONFIRMATION_EXIT_CODE,
    REJECTED_EXIT_CODE,
    SUCCESS_EXIT_CODE,
    UNEXPECTED_STATUS_EXIT_CODE,
    add_client_timing,
    exit_code_for_result,
    main,
    preflight_paper_order,
    request_json,
    workflow_error_payload,
)


class OpenClawTradingClientTests(unittest.TestCase):
    def test_paper_submitted_is_success(self) -> None:
        result = {
            "status": "PAPER_LIMIT_SUBMITTED",
            "approved": True,
            "pending_confirmation": False,
        }

        self.assertEqual(exit_code_for_result("paper-limit", result), SUCCESS_EXIT_CODE)

    def test_pending_confirmation_is_not_reported_as_success(self) -> None:
        result = {
            "status": "PAPER_LIMIT_PENDING_CONFIRMATION",
            "approved": True,
            "pending_confirmation": True,
        }

        self.assertEqual(
            exit_code_for_result("paper-limit", result),
            PENDING_CONFIRMATION_EXIT_CODE,
        )

    def test_rejected_order_is_not_reported_as_success(self) -> None:
        result = {
            "status": "REJECTED",
            "approved": False,
            "reason": "Order value exceeds the configured maximum",
        }

        self.assertEqual(exit_code_for_result("paper-limit", result), REJECTED_EXIT_CODE)

    def test_validation_rejection_uses_rejected_exit_code(self) -> None:
        result = {
            "status": "REJECTED",
            "approved": False,
            "reason": "Trading is DISARMED",
        }

        self.assertEqual(exit_code_for_result("validate", result), REJECTED_EXIT_CODE)

    def test_unknown_order_status_is_not_reported_as_success(self) -> None:
        result = {
            "status": "BROKER_UNKNOWN",
            "approved": True,
            "pending_confirmation": False,
        }

        self.assertEqual(
            exit_code_for_result("paper-limit", result),
            UNEXPECTED_STATUS_EXIT_CODE,
        )

    def test_client_timing_is_added_to_result(self) -> None:
        result = {"status": "PAPER_LIMIT_SUBMITTED"}

        add_client_timing(result, 0.0, "2026-06-28T00:00:00+00:00")

        timings = result["timings"]
        self.assertIn("openclaw_command_total_ms", timings)
        self.assertEqual(
            timings["openclaw_command_started_at"],
            "2026-06-28T00:00:00+00:00",
        )
        self.assertIn("openclaw_command_finished_at", timings)

    @patch("openclaw.openclaw_trading_client.request_json")
    def test_preflight_rejects_non_trade_lock(self, request_json: object) -> None:
        request_json.return_value = {
            "lock_state": "DEV_LOCK",
            "tws": {"ready_for_orders": True},
        }

        with self.assertRaisesRegex(RuntimeError, "not in TRADE_LOCK"):
            preflight_paper_order()

    @patch("openclaw.openclaw_trading_client.request_json")
    def test_preflight_rejects_tws_not_ready(self, request_json: object) -> None:
        request_json.return_value = {
            "lock_state": "TRADE_LOCK",
            "tws": {
                "ready_for_orders": False,
                "error": "TWS API is not reachable",
            },
        }

        with self.assertRaisesRegex(RuntimeError, "IBKR TWS is not ready"):
            preflight_paper_order()

    @patch("openclaw.openclaw_trading_client.urllib.request.urlopen")
    @patch("openclaw.openclaw_trading_client.load_secret")
    def test_api_connection_failure_reports_client_http(
        self,
        load_secret: object,
        urlopen: object,
    ) -> None:
        import urllib.error

        load_secret.return_value = "test-api-key"
        urlopen.side_effect = urllib.error.URLError("connection refused")

        with self.assertRaises(RuntimeError) as caught:
            request_json("GET", "/health")

        payload = workflow_error_payload(caught.exception)
        self.assertEqual(payload["workflow_step"], "client_http")
        self.assertIn("Could not reach Trading API", payload["error"])

    @patch("openclaw.openclaw_trading_client.preflight_paper_order")
    @patch("openclaw.openclaw_trading_client.request_json")
    @patch("openclaw.openclaw_trading_client.load_secret")
    @patch(
        "sys.argv",
        [
            "openclaw_trading_client.py",
            "paper-limit",
            "--fast",
            "--symbol",
            "MSFT",
            "--side",
            "BUY",
            "--quantity",
            "1",
            "--limit-price",
            "410",
            "--idempotency-key",
            "fast-limit-0001",
        ],
    )
    def test_fast_paper_limit_skips_client_preflight(
        self,
        load_secret: object,
        request_json: object,
        preflight: object,
    ) -> None:
        load_secret.return_value = "session-ok"
        request_json.return_value = {
            "status": "PAPER_LIMIT_SUBMITTED",
            "approved": True,
            "pending_confirmation": False,
        }

        output = StringIO()
        with redirect_stdout(output):
            exit_code = main()

        self.assertEqual(exit_code, SUCCESS_EXIT_CODE)
        preflight.assert_not_called()
        request_json.assert_called_once()
        method, path, payload = request_json.call_args.args
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/v1/orders/paper/limit")
        self.assertEqual(payload["trade_session_token"], "session-ok")
        result = json.loads(output.getvalue())
        self.assertEqual(result["openclaw_execution_mode"], "fast_trade_check")
        self.assertTrue(result["timings"]["openclaw_fast_mode"])


if __name__ == "__main__":
    unittest.main()
