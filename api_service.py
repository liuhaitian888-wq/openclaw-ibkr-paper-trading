"""Authenticated JSON API for OpenClaw-to-Python trading requests."""

import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict
from urllib.parse import parse_qs, unquote, urlparse

from trading.config import Settings
from trading.service import TradingService
from trading.workflow import workflow_error_payload


MAX_BODY_BYTES = 64 * 1024


class TradingApiHandler(BaseHTTPRequestHandler):
    service: TradingService

    def do_GET(self) -> None:  # noqa: N802
        if not self._authenticated():
            self._send_json(
                401,
                {
                    "status": "ERROR",
                    "workflow_step": "api_auth",
                    "error": "unauthorized",
                },
            )
            return
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self._send_json(200, self.service.health())
                return
            if parsed.path == "/v1/orders/audit":
                query = parse_qs(parsed.query)
                day = query.get("date", [None])[0]
                timezone_name = query.get("timezone", ["Europe/Berlin"])[0]
                limit = int(query.get("limit", ["50"])[0])
                result = self.service.audit_orders(
                    day=day,
                    timezone_name=timezone_name,
                    limit=limit,
                )
                self._send_json(200, result)
                return
            if parsed.path.startswith("/v1/orders/audit/"):
                idempotency_key = unquote(
                    parsed.path.removeprefix("/v1/orders/audit/")
                )
                if not idempotency_key:
                    self._send_json(404, {"error": "not_found"})
                    return
                self._send_json(200, self.service.audit_order(idempotency_key))
                return
            self._send_json(404, {"error": "not_found"})
        except KeyError:
            self._send_json(404, {"error": "order_not_found"})
        except ValueError as exc:
            self._send_json(400, workflow_error_payload(exc, "api_request_body"))
        except Exception as exc:
            payload = workflow_error_payload(exc, "api_request_body")
            payload["error_type"] = "internal_error"
            self._send_json(500, payload)

    def do_POST(self) -> None:  # noqa: N802
        if not self._authenticated():
            self._send_json(
                401,
                {
                    "status": "ERROR",
                    "workflow_step": "api_auth",
                    "error": "unauthorized",
                },
            )
            return
        try:
            path = urlparse(self.path).path
            payload = self._read_json()
            if path == "/v1/orders/validate":
                result = self.service.validate(payload)
            elif path == "/v1/orders/validate/limit":
                result = self.service.validate_limit(payload)
            elif path == "/v1/orders/stage":
                result = self.service.submit(payload, transmit=False)
            elif path == "/v1/orders/stage/limit":
                result = self.service.submit_limit(payload, transmit=False)
            elif path == "/v1/orders/paper":
                result = self.service.submit(payload, transmit=True)
            elif path == "/v1/orders/paper/limit":
                result = self.service.submit_limit(payload, transmit=True)
            else:
                self._send_json(404, {"error": "not_found"})
                return
            self._send_json(200, result)
        except PermissionError as exc:
            self._send_json(403, workflow_error_payload(exc, "service_gate"))
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(400, workflow_error_payload(exc, "api_request_body"))
        except Exception as exc:
            payload = workflow_error_payload(exc, "service_broker_submit")
            payload["error_type"] = "internal_error"
            self._send_json(500, payload)

    def log_message(self, format: str, *args: object) -> None:
        # Avoid standard-library access logs leaking request details.
        return

    def _authenticated(self) -> bool:
        provided = self.headers.get("X-API-Key", "")
        return hmac.compare_digest(provided, self.service.settings.api_key)

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ValueError("invalid request body size")
        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    settings = Settings.load()
    TradingApiHandler.service = TradingService(settings)
    server = ThreadingHTTPServer((settings.api_host, settings.api_port), TradingApiHandler)
    print(f"Trading API listening on http://{settings.api_host}:{settings.api_port}")
    print(f"Mode: {settings.trading_mode}; paper transmit: {settings.allow_paper_transmit}")
    server.serve_forever()


if __name__ == "__main__":
    main()
