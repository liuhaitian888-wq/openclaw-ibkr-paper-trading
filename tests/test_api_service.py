import json
import unittest
from io import BytesIO
from typing import Any, Dict, Mapping, Tuple

from api_service import TradingApiHandler
from trading.workflow import attach_workflow_step


class FakeSettings:
    api_key = "test-api-key"


class FakeService:
    settings = FakeSettings()

    def __init__(self) -> None:
        self.limit_submission: Tuple[Mapping[str, Any], bool] | None = None

    def submit_limit(self, payload: Mapping[str, Any], transmit: bool) -> Dict[str, Any]:
        self.limit_submission = (payload, transmit)
        return {"status": "LIMIT_STAGED_NOT_TRANSMITTED", "approved": True}


class FailingService(FakeService):
    def submit_limit(self, payload: Mapping[str, Any], transmit: bool) -> Dict[str, Any]:
        raise attach_workflow_step(
            PermissionError("TWS is not ready for orders: offline"),
            "service_tws_preflight",
        )


class CapturingHandler(TradingApiHandler):
    def __init__(self) -> None:
        self.status: int | None = None
        self.headers_sent: Dict[str, str] = {}

    def send_response(self, code: int, message: str | None = None) -> None:
        self.status = code

    def send_header(self, keyword: str, value: str) -> None:
        self.headers_sent[keyword] = value

    def end_headers(self) -> None:
        return


class ApiServiceTests(unittest.TestCase):
    def test_stage_limit_route_submits_without_transmission(self) -> None:
        service = FakeService()
        TradingApiHandler.service = service
        payload = {
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": 1,
            "limit_price": 190.0,
            "idempotency_key": "stage-limit-0001",
        }
        body = json.dumps(payload).encode("utf-8")
        handler = CapturingHandler()
        handler.path = "/v1/orders/stage/limit"
        handler.headers = {
            "Content-Length": str(len(body)),
            "X-API-Key": "test-api-key",
        }
        handler.rfile = BytesIO(body)
        handler.wfile = BytesIO()

        handler.do_POST()

        result = json.loads(handler.wfile.getvalue())
        self.assertEqual(handler.status, 200)
        self.assertEqual(result["status"], "LIMIT_STAGED_NOT_TRANSMITTED")
        self.assertIsNotNone(service.limit_submission)
        submitted_payload, transmit = service.limit_submission
        self.assertEqual(submitted_payload["idempotency_key"], "stage-limit-0001")
        self.assertFalse(transmit)

    def test_error_response_includes_workflow_step(self) -> None:
        TradingApiHandler.service = FailingService()
        payload = {
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": 1,
            "limit_price": 190.0,
            "idempotency_key": "stage-limit-0002",
        }
        body = json.dumps(payload).encode("utf-8")
        handler = CapturingHandler()
        handler.path = "/v1/orders/stage/limit"
        handler.headers = {
            "Content-Length": str(len(body)),
            "X-API-Key": "test-api-key",
        }
        handler.rfile = BytesIO(body)
        handler.wfile = BytesIO()

        handler.do_POST()

        result = json.loads(handler.wfile.getvalue())
        self.assertEqual(handler.status, 403)
        self.assertEqual(result["status"], "ERROR")
        self.assertEqual(result["workflow_step"], "service_tws_preflight")
        self.assertIn("TWS", result["error"])


if __name__ == "__main__":
    unittest.main()
