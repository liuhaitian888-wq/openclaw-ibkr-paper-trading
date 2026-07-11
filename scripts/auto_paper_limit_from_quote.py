"""Create a paper limit order from the latest IBKR quote.

This is the fast local execution harness for testing the full paper-trading
path. It reads a quote, builds a limit proposal, validates it, and optionally
submits it to the Mac Python trading API.
"""

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

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.config import Settings
from trading.ibkr_readonly import IbkrReadOnlyQuoteSource
from trading.market_data import Quote


DEFAULT_API_URL = "http://127.0.0.1:8787"
DEFAULT_TOKEN_FILES = (
    Path.home() / "Documents/openclaw_shared/trade_session_token",
    Path("/Volumes/openclaw_shared/trade_session_token"),
    Path("/mnt/openclaw_shared/trade_session_token"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument("--side", choices=("BUY", "SELL"), default="BUY")
    parser.add_argument("--quantity", type=int, default=1)
    parser.add_argument(
        "--mode",
        choices=("validate", "stage", "paper"),
        default="validate",
        help="validate is safest; stage sends to TWS without transmit; paper transmits paper order.",
    )
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--api-timeout", type=float, default=30.0)
    parser.add_argument("--api-key-file", type=Path, default=PROJECT_ROOT / ".secrets" / "openclaw_api_key")
    parser.add_argument(
        "--trade-session-token-file",
        type=Path,
        action="append",
        default=list(DEFAULT_TOKEN_FILES),
        help="Token file path. Can be supplied more than once.",
    )
    parser.add_argument("--idempotency-prefix", default="auto-limit")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--client-id", type=int, default=940)
    parser.add_argument("--quote-timeout", type=float, default=8.0)
    parser.add_argument("--exchange", default="SMART")
    parser.add_argument("--market-data-type", type=int, default=3)
    parser.add_argument(
        "--limit-offset-bps",
        type=float,
        default=0.0,
        help="For BUY, add this many bps to ask/mid/last. For SELL, subtract from bid/mid/last.",
    )
    parser.add_argument("--max-spread-bps", type=float, default=80.0)
    parser.add_argument("--max-quote-age-ms", type=float, default=5000.0)
    return parser.parse_args()


def main() -> int:
    started = time.perf_counter()
    args = parse_args()
    timeline = []

    health = request_json(
        "GET",
        "/health",
        None,
        api_url=args.api_url,
        api_key=read_required(args.api_key_file, "OPENCLAW_API_KEY"),
        timeout=args.api_timeout,
    )
    timeline.append(step("gateway_health", "ok", health.get("lock_state", "unknown")))

    quote = latest_quote(args)
    if quote is None:
        result = {
            "status": "BLOCKED",
            "workflow_step": "quote_fetch",
            "reason": "No IBKR quote returned",
            "timeline": timeline,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    timeline.append(
        step(
            "quote_fetch",
            "ok",
            f"{quote.symbol} last={quote.last} bid={quote.bid} ask={quote.ask} age_ms={quote.age_ms()}",
        )
    )

    spread_bps = quote_spread_bps(quote)
    if spread_bps is not None and spread_bps > args.max_spread_bps:
        result = {
            "status": "BLOCKED",
            "workflow_step": "spread_gate",
            "reason": f"Spread {spread_bps:.2f} bps exceeds max {args.max_spread_bps:.2f} bps",
            "quote": quote_payload(quote),
            "timeline": timeline,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 3
    timeline.append(step("spread_gate", "ok", "n/a" if spread_bps is None else f"{spread_bps:.2f} bps"))

    quote_age_ms = quote.age_ms()
    if quote_age_ms > args.max_quote_age_ms:
        result = {
            "status": "BLOCKED",
            "workflow_step": "freshness_gate",
            "reason": f"Quote age {quote_age_ms:.0f} ms exceeds max {args.max_quote_age_ms:.0f} ms",
            "quote": quote_payload(quote),
            "timeline": timeline,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 4
    timeline.append(step("freshness_gate", "ok", f"{quote_age_ms:.0f} ms"))

    payload = order_payload(args, quote)
    api_key = read_required(args.api_key_file, "OPENCLAW_API_KEY")
    if args.mode == "paper":
        payload["trade_session_token"] = read_trade_session_token(
            args.trade_session_token_file,
            "TRADE_SESSION_TOKEN",
        )
        endpoint = "/v1/orders/paper/limit"
    elif args.mode == "stage":
        endpoint = "/v1/orders/stage/limit"
    else:
        endpoint = "/v1/orders/validate/limit"

    submit_started = time.perf_counter()
    response = request_json(
        "POST",
        endpoint,
        payload,
        api_url=args.api_url,
        api_key=api_key,
        timeout=args.api_timeout,
    )
    response.setdefault("timings", {})["auto_harness_api_round_trip_ms"] = elapsed_ms(submit_started)
    response["auto_harness"] = {
        "mode": args.mode,
        "endpoint": endpoint,
        "quote": quote_payload(quote),
        "spread_bps": spread_bps,
        "idempotency_key": payload["idempotency_key"],
        "timeline": timeline,
        "total_ms": elapsed_ms(started),
    }
    print(json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if response.get("approved") is not False else 5


def latest_quote(args: argparse.Namespace) -> Optional[Quote]:
    settings = Settings.load()
    source = IbkrReadOnlyQuoteSource(
        host=args.host or settings.tws_host,
        port=args.port or settings.tws_port,
        client_id=args.client_id,
        timeout=args.quote_timeout,
        snapshot=True,
        market_data_type=args.market_data_type,
        exchange=args.exchange,
    )
    quotes = source.get_quotes([args.symbol])
    return quotes[0] if quotes else None


def order_payload(args: argparse.Namespace, quote: Quote) -> Dict[str, Any]:
    limit_price = calculate_limit_price(args.side, quote, args.limit_offset_bps)
    idempotency_key = (
        f"{args.idempotency_prefix}-{args.symbol.upper()}-"
        f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    )
    return {
        "symbol": args.symbol.upper(),
        "side": args.side,
        "quantity": args.quantity,
        "limit_price": limit_price,
        "idempotency_key": idempotency_key,
        "source": "auto_paper_limit_from_quote",
    }


def calculate_limit_price(side: str, quote: Quote, offset_bps: float) -> float:
    if side == "BUY":
        base = quote.ask or quote.midpoint or quote.last
        price = base * (1 + offset_bps / 10_000)
    else:
        base = quote.bid or quote.midpoint or quote.last
        price = base * (1 - offset_bps / 10_000)
    return round(float(price), 2)


def quote_spread_bps(quote: Quote) -> Optional[float]:
    if quote.spread is None:
        return None
    reference = quote.midpoint or quote.last
    if reference <= 0:
        return None
    return quote.spread / reference * 10_000


def quote_payload(quote: Quote) -> Dict[str, Any]:
    return {
        "symbol": quote.symbol,
        "last": quote.last,
        "bid": quote.bid,
        "ask": quote.ask,
        "close": quote.close,
        "volume": quote.volume,
        "age_ms": quote.age_ms(),
        "timestamp": quote.timestamp.isoformat(),
        "source": quote.source,
    }


def request_json(
    method: str,
    path: str,
    payload: Optional[Dict[str, Any]],
    *,
    api_url: str,
    api_key: str,
    timeout: float,
) -> Dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        api_url.rstrip("/") + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json", "X-API-Key": api_key},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
            if isinstance(data, dict):
                return data
            raise RuntimeError("Trading API returned non-object JSON")
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Trading API returned HTTP {exc.code}: {details}") from exc


def read_required(path: Path, name: str) -> str:
    try:
        value = path.expanduser().read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise RuntimeError(f"{name} file not found: {path}") from exc
    if not value:
        raise RuntimeError(f"{name} file is empty: {path}")
    return value


def read_trade_session_token(paths: list[Path], name: str) -> str:
    configured = os.getenv(name)
    if configured and configured.strip():
        return configured.strip()
    for path in paths:
        try:
            value = path.expanduser().read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            continue
        if value:
            return value
    formatted_paths = ", ".join(str(path) for path in paths)
    raise RuntimeError(f"{name} not found in env or token files: {formatted_paths}")


def step(name: str, status: str, detail: str) -> Dict[str, str]:
    return {"step": name, "status": status, "detail": detail}


def elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "ERROR",
                    "workflow_step": getattr(exc, "workflow_step", "auto_harness"),
                    "error": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1)
