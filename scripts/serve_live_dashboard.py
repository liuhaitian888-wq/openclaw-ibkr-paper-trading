"""Serve the IBKR read-only dashboard from localhost.

The server keeps a single read-only market-data refresh path into TWS and serves
cached dashboard data to browser tabs. This script does not place orders.
"""

import argparse
import copy
import json
import os
import random
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import parse_qs, urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.dashboard import render_dashboard_html
from trading.simulation import StrategySimulationConfig, run_strategy_simulation


DEFAULT_SYMBOLS = "AAPL,MSFT,NVDA,TSLA,AMD,INTC,NFLX"
_CLIENT_ID_LOCK = threading.Lock()
_CLIENT_ID_COUNTER = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    parser.add_argument("--refresh-seconds", type=float, default=10.0)
    parser.add_argument("--ibkr-host")
    parser.add_argument("--ibkr-port", type=int)
    parser.add_argument("--ibkr-client-id", type=int, default=120)
    parser.add_argument("--ibkr-timeout", type=float, default=12.0)
    parser.add_argument("--ibkr-exchange", default="SMART")
    parser.add_argument("--ibkr-market-data-type", type=int, default=3)
    parser.add_argument("--ibkr-workers", type=int, default=1)
    parser.add_argument("--ibkr-symbols-per-worker", type=int, default=8)
    parser.add_argument(
        "--quote-fallback-source",
        choices=("off", "simulated", "yahoo", "yahoo-replay", "stooq"),
        default="off",
        help="Source used for dashboard quotes when IBKR market data returns no quotes.",
    )
    parser.add_argument(
        "--trading-api-url",
        default="http://192.168.64.1:8787",
        help="Mac Python trading API base URL for /health status.",
    )
    return parser.parse_args()


def parse_symbols(raw_symbols: str) -> list[str]:
    return [symbol.strip().upper() for symbol in raw_symbols.split(",") if symbol.strip()]


class LiveDataCache:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self._lock = threading.Lock()
        self._data: dict[str, object] | None = None
        self._symbols_key: tuple[str, ...] = ()
        self._last_refresh_monotonic = 0.0

    def get(self, symbols: list[str]) -> dict[str, object]:
        symbols_key = tuple(symbols)
        now = time.monotonic()
        max_age = max(1.0, float(self.args.refresh_seconds))
        with self._lock:
            is_stale = (
                self._data is None
                or symbols_key != self._symbols_key
                or now - self._last_refresh_monotonic >= max_age
            )
            status = "cached"
            if is_stale:
                self._data = fetch_data(self.args, symbols)
                self._symbols_key = symbols_key
                self._last_refresh_monotonic = time.monotonic()
                status = "fresh"
            age_seconds = max(0.0, time.monotonic() - self._last_refresh_monotonic)
            return self._with_cache_status(self._data, status, age_seconds)

    def _with_cache_status(
        self,
        data: dict[str, object],
        status: str,
        age_seconds: float,
    ) -> dict[str, object]:
        result = copy.deepcopy(data)
        system_status = dict(result.get("system_status", {}))
        system_status["dashboard_cache"] = {
            "status": status,
            "age_seconds": round(age_seconds, 3),
            "refresh_seconds": self.args.refresh_seconds,
            "single_flight": True,
        }
        result["system_status"] = system_status
        return result


def fetch_data(args: argparse.Namespace, symbols: list[str]) -> dict[str, object]:
    client_id = next_client_id(args.ibkr_client_id)
    primary_data = run_strategy_simulation(
        StrategySimulationConfig(
            symbols=symbols,
            steps=1,
            source="ibkr-readonly",
            ibkr_host=args.ibkr_host,
            ibkr_port=args.ibkr_port,
            ibkr_client_id=client_id,
            ibkr_timeout=args.ibkr_timeout,
            ibkr_market_data_type=args.ibkr_market_data_type,
            ibkr_exchange=args.ibkr_exchange,
            ibkr_workers=args.ibkr_workers,
            ibkr_symbols_per_worker=args.ibkr_symbols_per_worker,
        )
    )
    primary_returned_symbols = list(primary_data.get("returned_symbols", []))
    primary_feed_errors = [str(error) for error in primary_data.get("feed_errors", [])]
    data = primary_data
    fallback_active = False
    fallback_source = None

    if not primary_returned_symbols and args.quote_fallback_source != "off":
        fallback_source = args.quote_fallback_source
        fallback_data = run_strategy_simulation(
            StrategySimulationConfig(
                symbols=symbols,
                steps=1,
                source=fallback_source,
            )
        )
        fallback_data["primary_source"] = primary_data.get("source", "ibkr-readonly")
        fallback_data["source"] = f"{fallback_source} fallback"
        fallback_data["primary_returned_symbols"] = primary_returned_symbols
        fallback_data["primary_feed_errors"] = primary_feed_errors
        fallback_data["feed_errors"] = primary_feed_errors + [
            f"dashboard quote fallback active: {fallback_source}"
        ]
        data = fallback_data
        fallback_active = True

    data["system_status"] = build_system_status(
        data,
        client_id,
        args.trading_api_url,
        primary_returned_symbols=primary_returned_symbols,
        primary_feed_errors=primary_feed_errors,
        fallback_active=fallback_active,
        fallback_source=fallback_source,
    )
    return data


def next_client_id(base_client_id: int) -> int:
    global _CLIENT_ID_COUNTER
    with _CLIENT_ID_LOCK:
        _CLIENT_ID_COUNTER += 1
        # Separate server processes and overlapping browser refreshes should not
        # collide on the same TWS API client id. Keep the value comfortably below
        # a signed 32-bit integer for TWS.
        entropy = random.SystemRandom().randint(1_000, 1_900_000_000)
        return base_client_id + entropy + _CLIENT_ID_COUNTER


def build_system_status(
    data: dict[str, object],
    client_id: int,
    trading_api_url: str,
    primary_returned_symbols: list[str] | None = None,
    primary_feed_errors: list[str] | None = None,
    fallback_active: bool = False,
    fallback_source: str | None = None,
) -> dict[str, object]:
    feed_errors = (
        primary_feed_errors
        if primary_feed_errors is not None
        else [str(error) for error in data.get("feed_errors", [])]
    )
    returned_symbols = (
        primary_returned_symbols
        if primary_returned_symbols is not None
        else data.get("returned_symbols", [])
    )
    gateway_health = fetch_trading_api_health(trading_api_url)
    market_data_ok = bool(returned_symbols)
    tws_connected = not any(
        "TWS API handshake timed out" in error
        or "Unable to connect" in error
        or "Connection refused" in error
        for error in feed_errors
    )
    client_id_conflict = any("client id is already in use" in error for error in feed_errors)
    subscription_blocked = any("subscription" in error.lower() for error in feed_errors)
    competing_live_session = any(
        "competing live session" in error.lower() for error in feed_errors
    )
    market_data_farm_broken = any(
        "market data farm connection is broken" in error.lower()
        for error in feed_errors
    )

    if client_id_conflict:
        python_to_tws = "blocked: TWS client id conflict"
    elif not tws_connected:
        python_to_tws = "blocked: TWS API unreachable or not logged in"
    elif market_data_ok:
        python_to_tws = "ok: IBKR read-only quotes returned"
    elif competing_live_session:
        python_to_tws = "connected: market data blocked by competing live session"
    elif market_data_farm_broken:
        python_to_tws = "connected: IBKR market data farm disconnected"
    elif subscription_blocked:
        python_to_tws = "blocked: market data subscription/API permission"
    else:
        python_to_tws = "connected: no market data quotes returned"
    if fallback_active and not market_data_ok:
        python_to_tws = f"{python_to_tws}; dashboard using {fallback_source} fallback"

    token_status = {
        "OPENCLAW_API_KEY": token_present(
            "OPENCLAW_API_KEY",
            PROJECT_ROOT / ".secrets" / "openclaw_api_key",
        ),
        "TRADE_SESSION_TOKEN": bool(gateway_health.get("trade_session_required"))
        or token_present("TRADE_SESSION_TOKEN", None)
        or token_present_file_from_env("TRADE_SESSION_TOKEN_FILE")
        or token_present_file(Path.home() / "Documents/openclaw_shared/trade_session_token")
        or token_present_file(Path("/Volumes/openclaw_shared/trade_session_token")),
        "DISCORD_BOT_TOKEN": token_present("DISCORD_BOT_TOKEN", None),
    }
    gateway_ok = gateway_health.get("status") == "ok"
    lock_state = gateway_health.get("lock_state", "unknown")
    paper_transmit = gateway_health.get("paper_transmit_enabled")
    kill_switch = gateway_health.get("kill_switch_enabled")
    gateway_tws = gateway_health.get("tws") if isinstance(gateway_health.get("tws"), dict) else {}

    return {
        "python_to_tws": python_to_tws,
        "tws_connected": tws_connected,
        "market_data_ok": market_data_ok,
        "market_data_errors": feed_errors,
        "quote_fallback": {
            "active": fallback_active,
            "source": fallback_source,
            "dashboard_quotes_returned": bool(data.get("returned_symbols", [])),
        },
        "client_id": client_id,
        "dashboard_to_trading_api": (
            f"ok: {lock_state}"
            if gateway_ok
            else f"blocked: {gateway_health.get('error', 'trading API /health unreachable')}"
        ),
        "python_to_openclaw": "not checked: OpenClaw runs outside this dashboard",
        "openclaw_to_python": (
            "likely ok if OpenClaw uses the same API URL/key; verify from OpenClaw VM"
            if gateway_ok
            else "blocked until trading API /health is reachable"
        ),
        "trading_api": {
            "url": trading_api_url,
            "reachable": gateway_ok,
            "lock_state": lock_state,
            "mode": gateway_health.get("mode"),
            "paper_transmit_enabled": paper_transmit,
            "kill_switch_enabled": kill_switch,
            "tws_ready_for_orders": gateway_tws.get("ready_for_orders"),
        },
        "tokens": token_status,
    }


def fetch_trading_api_health(base_url: str) -> dict[str, Any]:
    api_key = read_text_file(PROJECT_ROOT / ".secrets" / "openclaw_api_key")
    if not api_key:
        return {"status": "ERROR", "error": "OPENCLAW_API_KEY file missing"}
    url = base_url.rstrip("/") + "/health"
    request = Request(url, headers={"X-API-Key": api_key})
    try:
        with urlopen(request, timeout=2.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
            if isinstance(payload, dict):
                return payload
    except HTTPError as exc:
        return {"status": "ERROR", "error": f"HTTP {exc.code} from trading API /health"}
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return {"status": "ERROR", "error": str(exc)}
    return {"status": "ERROR", "error": "invalid trading API /health payload"}


def token_present(env_name: str, fallback_file: Path | None) -> bool:
    if os.getenv(env_name):
        return True
    return token_present_file(fallback_file) if fallback_file is not None else False


def token_present_file_from_env(env_name: str) -> bool:
    value = os.getenv(env_name)
    if not value:
        return False
    return token_present_file(Path(value).expanduser())


def token_present_file(path: Path | None) -> bool:
    if path is None:
        return False
    try:
        return path.exists() and bool(read_text_file(path))
    except OSError:
        return False


def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def make_handler(args: argparse.Namespace) -> type[BaseHTTPRequestHandler]:
    default_symbols = parse_symbols(args.symbols)
    cache = LiveDataCache(args)

    class LiveDashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self._send_json({"ok": True, "source": "ibkr-readonly"})
                return
            if parsed.path not in {"/", "/index.html", "/data.json"}:
                self.send_error(404)
                return

            query = parse_qs(parsed.query)
            symbols = parse_symbols(query.get("symbols", [",".join(default_symbols)])[0])
            data = cache.get(symbols)
            if parsed.path == "/data.json":
                self._send_json(data)
                return

            html = render_dashboard_html(
                data,
                auto_refresh_seconds=args.refresh_seconds,
            )
            self._send_bytes(html.encode("utf-8"), "text/html; charset=utf-8")

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send_json(self, payload: dict[str, object]) -> None:
            self._send_bytes(
                json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
                "application/json; charset=utf-8",
            )

        def _send_bytes(self, body: bytes, content_type: str) -> None:
            try:
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                return

    return LiveDashboardHandler


def main() -> int:
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(args))
    print(f"IBKR live dashboard: http://{args.host}:{args.port}/")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
