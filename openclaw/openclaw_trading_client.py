"""OpenClaw client for the Mac Python IBKR paper-trading gateway."""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote, urlencode


DEFAULT_API_URL = "http://192.168.64.1:8787"
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_API_KEY_FILE = BASE_DIR / ".secrets" / "openclaw_api_key"
DEFAULT_TRADE_SESSION_TOKEN_FILE = Path("/mnt/openclaw_shared/trade_session_token")
CONFIRMED_ORDER_STATUSES = {
    "PAPER_SUBMITTED",
    "PAPER_LIMIT_SUBMITTED",
    "STAGED_NOT_TRANSMITTED",
    "LIMIT_STAGED_NOT_TRANSMITTED",
}
PENDING_ORDER_STATUSES = {
    "PAPER_PENDING_CONFIRMATION",
    "PAPER_LIMIT_PENDING_CONFIRMATION",
    "TWS_STAGE_PENDING_CONFIRMATION",
    "LIMIT_STAGE_PENDING_CONFIRMATION",
}
SUCCESS_EXIT_CODE = 0
REJECTED_EXIT_CODE = 2
PENDING_CONFIRMATION_EXIT_CODE = 3
UNEXPECTED_STATUS_EXIT_CODE = 4
WORKFLOW_STEP_MESSAGES = {
    "client_secret": "OpenClaw client could not load the API key or trade token.",
    "client_http": "OpenClaw client could not reach the Mac trading API.",
    "client_preflight": "OpenClaw client preflight rejected the request.",
    "api_auth": "Mac trading API rejected the API key.",
    "api_request_body": "Mac trading API could not read the JSON request body.",
    "service_parse": "Trading service could not parse the order proposal.",
    "service_risk": "Trading service risk validation rejected the order.",
    "service_gate": "Trading service mode, lock, or session gate blocked the order.",
    "service_tws_preflight": "Trading service could not confirm TWS readiness.",
    "service_audit_reserve": "Trading service could not reserve the audit record.",
    "service_broker_submit": "Trading service broker adapter could not submit to TWS.",
    "service_audit_update": "Trading service could not update the audit record.",
    "complete": "Workflow completed.",
}


def attach_workflow_step(exc: Exception, step: str) -> Exception:
    setattr(exc, "workflow_step", step)
    setattr(exc, "workflow_step_message", WORKFLOW_STEP_MESSAGES.get(step, step))
    return exc


def workflow_error_payload(exc: BaseException) -> Dict[str, Any]:
    step = getattr(exc, "workflow_step", "client_http")
    if not isinstance(step, str) or not step:
        step = "client_http"
    return {
        "status": "ERROR",
        "workflow_step": step,
        "workflow_step_message": WORKFLOW_STEP_MESSAGES.get(step, step),
        "error": str(exc),
    }


def load_secret(name: str, default_file: Optional[Path] = None) -> str:
    configured = os.getenv(name)
    if configured:
        return configured.strip()

    file_name = f"{name}_FILE"
    configured_file = os.getenv(file_name)
    paths = []
    if configured_file:
        paths.append(Path(configured_file).expanduser())
    if default_file is not None:
        paths.append(default_file)

    for path in paths:
        try:
            value = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            continue
        if value:
            return value
    return ""


def request_json(
    method: str,
    path: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    request_started = time.perf_counter()
    api_key = load_secret("OPENCLAW_API_KEY", DEFAULT_API_KEY_FILE)
    if not api_key:
        raise attach_workflow_step(
            RuntimeError(
                "OPENCLAW_API_KEY is not set and .secrets/openclaw_api_key was not found"
            ),
            "client_secret",
        )
    base_url = os.getenv("TRADING_API_URL", DEFAULT_API_URL).rstrip("/")
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        base_url + path,
        data=body,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            result = json.loads(response.read())
            if isinstance(result, dict):
                result.setdefault("timings", {})["openclaw_http_round_trip_ms"] = (
                    _elapsed_ms(request_started)
                )
            return result
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        error = RuntimeError(f"Trading API returned HTTP {exc.code}: {details}")
        try:
            parsed = json.loads(details)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            step = parsed.get("workflow_step")
            if isinstance(step, str) and step:
                attach_workflow_step(error, step)
        raise error from exc
    except urllib.error.URLError as exc:
        raise attach_workflow_step(
            RuntimeError(f"Could not reach Trading API: {exc.reason}"),
            "client_http",
        ) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("health")

    audit_parser = subparsers.add_parser("audit")
    audit_parser.add_argument("--date")
    audit_parser.add_argument("--timezone", default="Europe/Berlin")
    audit_parser.add_argument("--limit", type=int, default=50)

    audit_key_parser = subparsers.add_parser("audit-key")
    audit_key_parser.add_argument("idempotency_key")

    add_order_args(subparsers.add_parser("validate"))
    add_order_args(subparsers.add_parser("validate-limit"), require_stop=False)
    add_order_args(subparsers.add_parser("paper"), allow_fast=True)
    add_order_args(subparsers.add_parser("stage-limit"), require_stop=False)
    add_order_args(
        subparsers.add_parser("paper-limit"),
        require_stop=False,
        allow_fast=True,
    )
    return parser.parse_args()


def add_order_args(
    parser: argparse.ArgumentParser,
    require_stop: bool = True,
    allow_fast: bool = False,
) -> None:
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--side", choices=("BUY", "SELL"), required=True)
    parser.add_argument("--quantity", type=int, required=True)
    parser.add_argument("--limit-price", type=float, required=True)
    parser.add_argument("--stop-price", type=float, required=require_stop)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--source", default="openclaw")
    if allow_fast:
        parser.add_argument(
            "--fast",
            action="store_true",
            help=(
                "Skip the OpenClaw-side health preflight and rely on the Python "
                "gateway's final risk, lock, token, TWS preflight, and audit gates."
            ),
        )


def order_payload(args: argparse.Namespace) -> Dict[str, Any]:
    payload = {
        "symbol": args.symbol,
        "side": args.side,
        "quantity": args.quantity,
        "limit_price": args.limit_price,
        "idempotency_key": args.idempotency_key,
        "source": args.source,
    }
    if args.stop_price is not None:
        payload["stop_price"] = args.stop_price
    return payload


def preflight_paper_order() -> Dict[str, Any]:
    health = request_json("GET", "/health")
    lock_state = health.get("lock_state")
    tws = health.get("tws", {})
    if lock_state != "TRADE_LOCK":
        raise attach_workflow_step(
            RuntimeError(
                "Trading gateway is not in TRADE_LOCK: "
                + json.dumps(health, ensure_ascii=False, sort_keys=True)
            ),
            "client_preflight",
        )
    if not isinstance(tws, dict) or tws.get("ready_for_orders") is not True:
        raise attach_workflow_step(
            RuntimeError(
                "IBKR TWS is not ready for orders: "
                + json.dumps(health, ensure_ascii=False, sort_keys=True)
            ),
            "client_preflight",
        )
    return health


def exit_code_for_result(command: str, result: Dict[str, Any]) -> int:
    if command in {"health", "audit", "audit-key"}:
        return SUCCESS_EXIT_CODE

    if command in {"validate", "validate-limit"}:
        return SUCCESS_EXIT_CODE if result.get("approved") is True else REJECTED_EXIT_CODE

    status = result.get("status")
    if result.get("approved") is False or status == "REJECTED":
        return REJECTED_EXIT_CODE
    if result.get("pending_confirmation") is True or status in PENDING_ORDER_STATUSES:
        return PENDING_CONFIRMATION_EXIT_CODE
    if status in CONFIRMED_ORDER_STATUSES:
        return SUCCESS_EXIT_CODE
    return UNEXPECTED_STATUS_EXIT_CODE


def add_client_timing(result: Dict[str, Any], command_started: float, started_at: str) -> None:
    timings = result.setdefault("timings", {})
    timings["openclaw_command_total_ms"] = _elapsed_ms(command_started)
    timings["openclaw_command_started_at"] = started_at
    timings["openclaw_command_finished_at"] = _utc_now()


def add_execution_mode(result: Dict[str, Any], fast: bool) -> None:
    result["openclaw_execution_mode"] = "fast_trade_check" if fast else "standard"
    result.setdefault("timings", {})["openclaw_fast_mode"] = fast


def require_trade_session_token() -> str:
    trade_session_token = load_secret(
        "TRADE_SESSION_TOKEN",
        DEFAULT_TRADE_SESSION_TOKEN_FILE,
    )
    if not trade_session_token:
        raise attach_workflow_step(
            RuntimeError(
                "TRADE_SESSION_TOKEN is required for paper orders; set it or place it in /mnt/openclaw_shared/trade_session_token"
            ),
            "client_secret",
        )
    return trade_session_token


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    command_started = time.perf_counter()
    command_started_at = _utc_now()
    args = parse_args()
    if args.command == "health":
        result = request_json("GET", "/health")
    elif args.command == "audit":
        query: Dict[str, Any] = {"limit": args.limit}
        if args.date:
            query["date"] = args.date
            query["timezone"] = args.timezone
        result = request_json("GET", "/v1/orders/audit?" + urlencode(query))
    elif args.command == "audit-key":
        result = request_json(
            "GET",
            f"/v1/orders/audit/{quote(args.idempotency_key, safe='')}",
        )
    elif args.command == "validate":
        result = request_json(
            "POST",
            "/v1/orders/validate",
            order_payload(args),
        )
    elif args.command == "validate-limit":
        result = request_json(
            "POST",
            "/v1/orders/validate/limit",
            order_payload(args),
        )
    elif args.command == "paper":
        if not args.fast:
            preflight_paper_order()
        trade_session_token = require_trade_session_token()
        payload = order_payload(args)
        payload["trade_session_token"] = trade_session_token
        result = request_json("POST", "/v1/orders/paper", payload)
        add_execution_mode(result, args.fast)
    elif args.command == "stage-limit":
        result = request_json(
            "POST",
            "/v1/orders/stage/limit",
            order_payload(args),
        )
    else:
        if not args.fast:
            preflight_paper_order()
        trade_session_token = require_trade_session_token()
        payload = order_payload(args)
        payload["trade_session_token"] = trade_session_token
        result = request_json("POST", "/v1/orders/paper/limit", payload)
        add_execution_mode(result, args.fast)
    add_client_timing(result, command_started, command_started_at)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return exit_code_for_result(args.command, result)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps(workflow_error_payload(exc), ensure_ascii=False, sort_keys=True), file=sys.stderr)
        raise SystemExit(1)
