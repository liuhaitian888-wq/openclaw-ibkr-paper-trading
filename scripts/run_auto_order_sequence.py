"""Run an automatic module-style order sequence from current IBKR quotes.

The sequence is intentionally simple and auditable:
1. Check gateway health.
2. Read current quotes.
3. Apply quote freshness, spread, allowlist, and max order value gates.
4. Build one-share limit proposals.
5. Send each proposal to validate, stage, or paper endpoint.
6. Write a JSON run report under reports/.
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
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.config import Settings
from trading.ibkr_readonly import IbkrReadOnlyQuoteSource
from trading.market_data import Quote


DEFAULT_API_URL = "http://192.168.64.1:8787"
DEFAULT_TOKEN_FILES = (
    Path("/Volumes/openclaw_shared/trade_session_token"),
    Path("/mnt/openclaw_shared/trade_session_token"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="AAPL,MSFT,SPY")
    parser.add_argument("--mode", choices=("validate", "stage", "paper"), default="validate")
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--api-key-file", type=Path, default=PROJECT_ROOT / ".secrets" / "openclaw_api_key")
    parser.add_argument("--trade-session-token-file", type=Path, action="append", default=list(DEFAULT_TOKEN_FILES))
    parser.add_argument("--max-orders", type=int, default=3)
    parser.add_argument("--quantity", type=int, default=1)
    parser.add_argument("--max-spread-bps", type=float, default=80.0)
    parser.add_argument("--max-quote-age-ms", type=float, default=5000.0)
    parser.add_argument("--limit-offset-bps", type=float, default=0.0)
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--client-id", type=int, default=970)
    parser.add_argument("--quote-timeout", type=float, default=8.0)
    parser.add_argument("--exchange", default="SMART")
    parser.add_argument("--market-data-type", type=int, default=3)
    parser.add_argument("--api-timeout", type=float, default=30.0)
    parser.add_argument("--report-dir", type=Path, default=PROJECT_ROOT / "reports")
    return parser.parse_args()


def main() -> int:
    started = time.perf_counter()
    args = parse_args()
    api_key = read_required(args.api_key_file, "OPENCLAW_API_KEY")
    trade_session_token = (
        read_trade_session_token(args.trade_session_token_file)
        if args.mode == "paper"
        else None
    )
    try:
        health = request_json(
            "GET",
            "/health",
            None,
            api_url=args.api_url,
            api_key=api_key,
            timeout=args.api_timeout,
        )
    except Exception as exc:
        report = {
            "source": "run_auto_order_sequence",
            "mode": args.mode,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "ERROR",
            "workflow_step": "client_preflight",
            "workflow_step_message": "Could not reach Trading API /health before automatic order sequence.",
            "api_url": args.api_url,
            "error": str(exc),
            "timings": {"sequence_total_ms": elapsed_ms(started)},
        }
        report_path = write_report(args.report_dir, report)
        report["report_path"] = str(report_path)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    try:
        require_trade_lock(health)
    except Exception as exc:
        report = {
            "source": "run_auto_order_sequence",
            "mode": args.mode,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "ERROR",
            "workflow_step": "client_preflight",
            "workflow_step_message": "Trading API is reachable, but TRADE_LOCK/TWS readiness gates did not pass.",
            "api_url": args.api_url,
            "error": str(exc),
            "gateway": {
                "status": health.get("status"),
                "lock_state": health.get("lock_state"),
                "paper_transmit_enabled": health.get("paper_transmit_enabled"),
                "tws_ready_for_orders": (
                    health.get("tws", {}).get("ready_for_orders")
                    if isinstance(health.get("tws"), dict)
                    else None
                ),
            },
            "timings": {"sequence_total_ms": elapsed_ms(started)},
        }
        report_path = write_report(args.report_dir, report)
        report["report_path"] = str(report_path)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 3
    symbols = parse_symbols(args.symbols)
    quotes = fetch_quotes(args, symbols)
    quote_by_symbol = {quote.symbol.upper(): quote for quote in quotes}

    allowed_symbols = set(health.get("limits", {}).get("allowed_symbols", []))
    max_order_value = float(health.get("limits", {}).get("max_order_value", 0.0))
    proposals: List[Dict[str, Any]] = []
    decisions: List[Dict[str, Any]] = []

    for symbol in symbols:
        quote = quote_by_symbol.get(symbol)
        decision = evaluate_symbol(
            symbol=symbol,
            quote=quote,
            allowed_symbols=allowed_symbols,
            max_order_value=max_order_value,
            quantity=args.quantity,
            max_spread_bps=args.max_spread_bps,
            max_quote_age_ms=args.max_quote_age_ms,
            limit_offset_bps=args.limit_offset_bps,
        )
        decisions.append(decision)
        if decision["approved"] and len(proposals) < args.max_orders:
            proposals.append(decision["proposal"])

    endpoint = endpoint_for_mode(args.mode)
    results = []
    for proposal in proposals:
        payload = dict(proposal)
        if trade_session_token:
            payload["trade_session_token"] = trade_session_token
        order_started = time.perf_counter()
        order_started_at = utc_now()
        try:
            result = request_json(
                "POST",
                endpoint,
                payload,
                api_url=args.api_url,
                api_key=api_key,
                timeout=args.api_timeout,
            )
            result["sequence_order_round_trip_ms"] = elapsed_ms(order_started)
            result["sequence_order_started_at"] = order_started_at
            result["sequence_order_finished_at"] = utc_now()
            result["proposal"] = proposal
            result["tws_order_ref"] = proposal["idempotency_key"]
        except Exception as exc:
            result = {
                "status": "ERROR",
                "workflow_step": "sequence_order_submit",
                "error": str(exc),
                "proposal": proposal,
                "tws_order_ref": proposal["idempotency_key"],
                "sequence_order_started_at": order_started_at,
                "sequence_order_finished_at": utc_now(),
                "sequence_order_round_trip_ms": elapsed_ms(order_started),
            }
        results.append(result)

    report = {
        "source": "run_auto_order_sequence",
        "mode": args.mode,
        "endpoint": endpoint,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "symbols": symbols,
        "gateway": {
            "status": health.get("status"),
            "lock_state": health.get("lock_state"),
            "paper_transmit_enabled": health.get("paper_transmit_enabled"),
            "tws_ready_for_orders": (
                health.get("tws", {}).get("ready_for_orders")
                if isinstance(health.get("tws"), dict)
                else None
            ),
            "allowed_symbols": sorted(allowed_symbols),
            "max_order_value": max_order_value,
        },
        "quotes": [quote_payload(quote) for quote in quotes],
        "decisions": decisions,
        "submitted_count": len(results),
        "results": results,
        "timings": {
            "sequence_total_ms": elapsed_ms(started),
        },
    }
    report_path = write_report(args.report_dir, report)
    report["report_path"] = str(report_path)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def fetch_quotes(args: argparse.Namespace, symbols: List[str]) -> List[Quote]:
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
    return source.get_quotes(symbols)


def require_trade_lock(health: Dict[str, Any]) -> None:
    tws = health.get("tws", {}) if isinstance(health.get("tws"), dict) else {}
    if health.get("lock_state") != "TRADE_LOCK":
        raise RuntimeError(
            "AUTO sequence requires TRADE_LOCK; current lock_state="
            + str(health.get("lock_state"))
        )
    if health.get("paper_transmit_enabled") is not True:
        raise RuntimeError("AUTO sequence requires paper_transmit_enabled=true")
    if tws.get("ready_for_orders") is not True:
        raise RuntimeError("AUTO sequence requires TWS ready_for_orders=true")


def evaluate_symbol(
    *,
    symbol: str,
    quote: Optional[Quote],
    allowed_symbols: set[str],
    max_order_value: float,
    quantity: int,
    max_spread_bps: float,
    max_quote_age_ms: float,
    limit_offset_bps: float,
) -> Dict[str, Any]:
    reasons = []
    if quote is None:
        reasons.append("no quote")
    if symbol not in allowed_symbols:
        reasons.append("not in gateway allowlist")
    if quote is not None and quote.age_ms() > max_quote_age_ms:
        reasons.append("quote stale")
    spread_bps = quote_spread_bps(quote) if quote is not None else None
    if spread_bps is not None and spread_bps > max_spread_bps:
        reasons.append("spread too wide")
    limit_price = calculate_limit_price(quote, limit_offset_bps) if quote is not None else None
    if limit_price is not None and quantity * limit_price > max_order_value:
        reasons.append("order value exceeds gateway maximum")

    proposal = None
    if not reasons and limit_price is not None:
        proposal = {
            "symbol": symbol,
            "side": "BUY",
            "quantity": quantity,
            "limit_price": limit_price,
            "idempotency_key": (
                f"seq-{symbol.lower()}-"
                f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
            )[:64],
            "source": "auto_order_sequence",
        }
    return {
        "symbol": symbol,
        "approved": not reasons,
        "reasons": reasons,
        "quote": quote_payload(quote) if quote is not None else None,
        "spread_bps": spread_bps,
        "proposal": proposal,
    }


def calculate_limit_price(quote: Quote, offset_bps: float) -> float:
    base = quote.ask or quote.midpoint or quote.last
    return round(float(base) * (1 + offset_bps / 10_000), 2)


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


def endpoint_for_mode(mode: str) -> str:
    if mode == "paper":
        return "/v1/orders/paper/limit"
    if mode == "stage":
        return "/v1/orders/stage/limit"
    return "/v1/orders/validate/limit"


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


def parse_symbols(raw_symbols: str) -> List[str]:
    return [symbol.strip().upper() for symbol in raw_symbols.split(",") if symbol.strip()]


def read_required(path: Path, name: str) -> str:
    try:
        value = path.expanduser().read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise RuntimeError(f"{name} file not found: {path}") from exc
    if not value:
        raise RuntimeError(f"{name} file is empty: {path}")
    return value


def read_trade_session_token(paths: List[Path]) -> str:
    configured = os.getenv("TRADE_SESSION_TOKEN")
    if configured and configured.strip():
        return configured.strip()
    for path in paths:
        try:
            value = path.expanduser().read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            continue
        if value:
            return value
    raise RuntimeError("TRADE_SESSION_TOKEN not found")


def write_report(report_dir: Path, report: Dict[str, Any]) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / (
        "auto_order_sequence_"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + ".json"
    )
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


if __name__ == "__main__":
    raise SystemExit(main())
