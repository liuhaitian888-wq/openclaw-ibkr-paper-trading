"""Run the first modular pool strategy against validate/stage/paper endpoints.

The module is long-only and paper-oriented. It scans a rotating pool, keeps a
warm quote cache and per-symbol bar history, then submits small limit orders
through the existing Trading API safety gates.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.config import Settings
from trading.dashboard import render_dashboard_html
from trading.ibkr_readonly import IbkrReadOnlyQuoteSource
from trading.market_data import Quote, QuoteSource, SimulatedQuoteSource
from trading.simulation import default_profiles, value_pool_record
from trading.strategy import StrategyScannerConfig, RotatingStrategyScanner, ValueFilterConfig, ValuePoolFilter
from trading.strategy_modules import ConservativeTrendConfig, ConservativeTrendModule, ModuleDecision


DEFAULT_API_URL = "http://192.168.64.1:8787"
DEFAULT_TOKEN_FILES = (
    Path("/Volumes/openclaw_shared/trade_session_token"),
    Path("/mnt/openclaw_shared/trade_session_token"),
)
DEFAULT_POOL = "AAPL,MSFT,AMD,INTC,KO,PFE,T,F"


class ScenarioQuoteSource:
    def __init__(self, prices: Dict[str, Sequence[float]], interval_seconds: int = 60) -> None:
        self._prices = {symbol.upper(): list(values) for symbol, values in prices.items()}
        self._indexes = {symbol.upper(): 0 for symbol in prices}
        self._tick = 0
        self._interval_seconds = interval_seconds
        self._started_at = datetime.now(timezone.utc).replace(microsecond=0)
        self.last_errors: List[str] = []

    def get_quotes(self, symbols: Sequence[str]) -> List[Quote]:
        timestamp = self._started_at + timedelta(seconds=self._tick * self._interval_seconds)
        self._tick += 1
        quotes = []
        for raw_symbol in symbols:
            symbol = raw_symbol.upper()
            values = self._prices.get(symbol)
            if not values:
                continue
            index = self._indexes.get(symbol, 0)
            price = float(values[index % len(values)])
            self._indexes[symbol] = index + 1
            quotes.append(
                Quote(
                    symbol=symbol,
                    last=price,
                    bid=round(price * 0.9998, 2),
                    ask=round(price * 1.0002, 2),
                    close=price,
                    timestamp=timestamp,
                    source="simulated_scenario",
                    volume=1000,
                )
            )
        return quotes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default=DEFAULT_POOL)
    parser.add_argument("--mode", choices=("validate", "stage", "paper"), default="validate")
    parser.add_argument("--source", choices=("simulated-scenario", "simulated", "ibkr-readonly"), default="simulated-scenario")
    parser.add_argument("--steps", type=int, default=24)
    parser.add_argument("--batch-size", type=int, default=3)
    parser.add_argument("--poll-seconds", type=float, default=0.0)
    parser.add_argument("--max-orders", type=int, default=12)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--api-key-file", type=Path, default=PROJECT_ROOT / ".secrets" / "openclaw_api_key")
    parser.add_argument("--trade-session-token-file", type=Path, action="append", default=list(DEFAULT_TOKEN_FILES))
    parser.add_argument("--api-timeout", type=float, default=30.0)
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--client-id", type=int, default=980)
    parser.add_argument("--quote-timeout", type=float, default=8.0)
    parser.add_argument("--exchange", default="SMART")
    parser.add_argument("--market-data-type", type=int, default=3)
    parser.add_argument("--fast-window", type=int, default=2)
    parser.add_argument("--slow-window", type=int, default=3)
    parser.add_argument("--profit-target-pct", type=float, default=0.0015)
    parser.add_argument("--stop-loss-pct", type=float, default=0.0015)
    parser.add_argument("--min-gap-pct", type=float, default=0.0001)
    parser.add_argument("--cooldown-steps", type=int, default=0)
    parser.add_argument("--report-dir", type=Path, default=PROJECT_ROOT / "reports")
    parser.add_argument(
        "--dashboard-output",
        type=Path,
        default=PROJECT_ROOT / "dashboard" / "pool_strategy_dashboard.html",
    )
    return parser.parse_args()


def main() -> int:
    started = time.perf_counter()
    args = parse_args()
    api_key = read_required(args.api_key_file, "OPENCLAW_API_KEY")
    trade_session_token = read_trade_session_token(args.trade_session_token_file) if args.mode == "paper" else None
    health = request_json("GET", "/health", None, api_url=args.api_url, api_key=api_key, timeout=args.api_timeout)
    require_gateway_mode(health, args.mode)

    symbols = parse_symbols(args.symbols)
    allowed_symbols = sorted(set(health.get("limits", {}).get("allowed_symbols", [])))
    source = build_source(args, symbols)
    value_filter = ValuePoolFilter(ValueFilterConfig())
    value_pool = [value_pool_record(value_filter, profile) for profile in default_profiles()]
    approved_value_symbols = {item["symbol"] for item in value_pool if item["approved"] is True}
    module_symbols = [symbol for symbol in symbols if symbol in allowed_symbols]
    module_allowed = [symbol for symbol in module_symbols if symbol in approved_value_symbols or symbol not in {"QQQ", "SPY"}]

    scanner = RotatingStrategyScanner(
        source=source,
        symbols=symbols,
        allowed_symbols=module_allowed,
        config=StrategyScannerConfig(
            batch_size=args.batch_size,
            interval_seconds=60,
            bar_history_capacity=64,
        ),
    )
    module = ConservativeTrendModule(
        allowed_symbols=module_allowed,
        config=ConservativeTrendConfig(
            fast_window=args.fast_window,
            slow_window=args.slow_window,
            profit_target_pct=args.profit_target_pct,
            stop_loss_pct=args.stop_loss_pct,
            min_gap_pct=args.min_gap_pct,
            cooldown_steps=args.cooldown_steps,
        ),
    )

    scan_reports = []
    decisions = []
    submissions = []
    pnl_curve = []
    latest_quotes: Dict[str, Quote] = {}
    realized_pnl = 0.0
    submitted_count = 0
    for step in range(max(1, args.steps)):
        scan_report = scanner.scan_once()
        scan_reports.append(compact_scan_report(step, scan_report))
        for event in scan_report["events"]:
            symbol = str(event["symbol"])
            quote = scanner.cache.get(symbol)
            if quote is None:
                continue
            latest_quotes[symbol] = quote
            decision = module.evaluate(
                symbol=symbol,
                quote=quote,
                bars=scanner.bar_history.values(symbol),
                step=step,
            )
            decisions.append(decision_payload(step, decision))
            if not decision.is_order or submitted_count >= args.max_orders:
                continue
            payload = order_payload(decision, step)
            if trade_session_token:
                payload["trade_session_token"] = trade_session_token
            result = submit_order(args, api_key, payload)
            result["step"] = step
            result["decision"] = decision_payload(step, decision)
            result["proposal"] = payload_without_token(payload)
            submissions.append(result)
            if result.get("approved") is not False:
                realized_pnl += realized_pnl_for_decision(decision, module.positions)
                module.record_order_decision(decision, step)
                submitted_count += 1
        pnl_curve.append(pnl_snapshot(step, module.positions, latest_quotes, realized_pnl))
        if args.poll_seconds > 0 and step < args.steps - 1:
            time.sleep(args.poll_seconds)

    report = {
        "source": "run_pool_strategy_module",
        "module": ConservativeTrendModule.name,
        "mode": args.mode,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "symbols": symbols,
        "module_allowed_symbols": module_allowed,
        "gateway_allowed_symbols": allowed_symbols,
        "value_pool": value_pool,
        "returned_symbols": sorted(latest_quotes),
        "missing_symbols": [symbol for symbol in symbols if symbol not in latest_quotes],
        "cache": [quote_payload(quote) for quote in latest_quotes.values()],
        "batch_size": args.batch_size,
        "steps": args.steps,
        "submitted_count": len(submissions),
        "positions": {
            symbol: {
                "quantity": position.quantity,
                "entry_price": position.entry_price,
                "opened_step": position.opened_step,
            }
            for symbol, position in module.positions.items()
        },
        "pnl_curve": pnl_curve,
        "scan_reports": scan_reports,
        "decisions": decisions,
        "submissions": submissions,
        "timings": {"run_total_ms": elapsed_ms(started)},
    }
    report_path = write_report(args.report_dir, report)
    report["report_path"] = str(report_path)
    dashboard_path = write_dashboard(args.dashboard_output, report)
    report["dashboard_path"] = str(dashboard_path)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def build_source(args: argparse.Namespace, symbols: List[str]) -> QuoteSource:
    if args.source == "ibkr-readonly":
        settings = Settings.load()
        return IbkrReadOnlyQuoteSource(
            host=args.host or settings.tws_host,
            port=args.port or settings.tws_port,
            client_id=args.client_id,
            timeout=args.quote_timeout,
            snapshot=True,
            market_data_type=args.market_data_type,
            exchange=args.exchange,
        )
    if args.source == "simulated":
        return SimulatedQuoteSource(default_price_series(symbols))
    return ScenarioQuoteSource(scenario_price_series(symbols))


def scenario_price_series(symbols: List[str]) -> Dict[str, List[float]]:
    base = default_price_series(symbols)
    scenario = {}
    pattern = [1.0000, 1.0015, 1.0035, 1.0055, 1.0020, 0.9990, 0.9965, 0.9985]
    for symbol, prices in base.items():
        start = prices[0]
        scenario[symbol] = [round(start * factor, 2) for factor in pattern]
    return scenario


def default_price_series(symbols: List[str]) -> Dict[str, List[float]]:
    defaults = {
        "AAPL": [190.0],
        "MSFT": [330.0],
        "AMD": [145.0],
        "INTC": [34.0],
        "KO": [63.0],
        "PFE": [29.0],
        "T": [18.0],
        "F": [12.0],
        "SPY": [510.0],
        "QQQ": [440.0],
    }
    return {symbol: defaults.get(symbol, [80.0]) for symbol in symbols}


def endpoint_for_mode(mode: str) -> str:
    if mode == "paper":
        return "/v1/orders/paper/limit"
    if mode == "stage":
        return "/v1/orders/stage/limit"
    return "/v1/orders/validate/limit"


def submit_order(args: argparse.Namespace, api_key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    started = time.perf_counter()
    try:
        result = request_json(
            "POST",
            endpoint_for_mode(args.mode),
            payload,
            api_url=args.api_url,
            api_key=api_key,
            timeout=args.api_timeout,
        )
    except Exception as exc:
        result = {
            "status": "ERROR",
            "approved": False,
            "workflow_step": "module_order_submit",
            "error": str(exc),
        }
    result["module_order_round_trip_ms"] = elapsed_ms(started)
    return result


def order_payload(decision: ModuleDecision, step: int) -> Dict[str, Any]:
    return {
        "symbol": decision.symbol,
        "side": decision.side,
        "quantity": decision.quantity,
        "limit_price": decision.limit_price,
        "idempotency_key": (
            f"pool-{decision.symbol.lower()}-{decision.action.lower()}-"
            f"{step}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        )[:64],
        "source": ConservativeTrendModule.name,
    }


def decision_payload(step: int, decision: ModuleDecision) -> Dict[str, Any]:
    return {
        "step": step,
        "symbol": decision.symbol,
        "action": decision.action,
        "reason": decision.reason,
        "side": decision.side,
        "quantity": decision.quantity,
        "limit_price": decision.limit_price,
        "fast_ma": decision.fast_ma,
        "slow_ma": decision.slow_ma,
        "position_entry_price": decision.position_entry_price,
    }


def compact_scan_report(step: int, scan_report: Dict[str, object]) -> Dict[str, object]:
    return {
        "step": step,
        "requested_symbols": scan_report["requested_symbols"],
        "returned_symbols": scan_report["returned_symbols"],
        "missing_symbols": scan_report["missing_symbols"],
    }


def pnl_snapshot(
    step: int,
    positions: Dict[str, Any],
    latest_quotes: Dict[str, Quote],
    realized_pnl: float,
) -> Dict[str, object]:
    unrealized = 0.0
    market_value = 0.0
    position_count = 0
    for symbol, position in positions.items():
        quote = latest_quotes.get(symbol)
        if quote is None:
            continue
        position_count += 1
        market_value += position.quantity * quote.last
        unrealized += position.quantity * (quote.last - position.entry_price)
    return {
        "step": step,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "unrealized_pnl": round(unrealized, 4),
        "realized_pnl": round(realized_pnl, 4),
        "total_pnl": round(realized_pnl + unrealized, 4),
        "market_value": round(market_value, 4),
        "open_positions": position_count,
    }


def realized_pnl_for_decision(
    decision: ModuleDecision,
    positions: Dict[str, Any],
) -> float:
    if decision.side != "SELL" or decision.limit_price is None:
        return 0.0
    position = positions.get(decision.symbol)
    if position is None:
        return 0.0
    return decision.quantity * (decision.limit_price - position.entry_price)


def require_gateway_mode(health: Dict[str, Any], mode: str) -> None:
    if mode == "validate":
        return
    if health.get("lock_state") != "TRADE_LOCK":
        raise RuntimeError(f"{mode} requires TRADE_LOCK; current lock_state={health.get('lock_state')}")
    if health.get("paper_transmit_enabled") is not True:
        raise RuntimeError(f"{mode} requires paper_transmit_enabled=true")
    tws = health.get("tws", {}) if isinstance(health.get("tws"), dict) else {}
    if tws.get("ready_for_orders") is not True:
        raise RuntimeError(f"{mode} requires TWS ready_for_orders=true")


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
    value = path.expanduser().read_text(encoding="utf-8").strip()
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


def payload_without_token(payload: Dict[str, Any]) -> Dict[str, Any]:
    clean = dict(payload)
    clean.pop("trade_session_token", None)
    return clean


def quote_payload(quote: Quote) -> Dict[str, Any]:
    return {
        "symbol": quote.symbol,
        "last": quote.last,
        "bid": quote.bid,
        "ask": quote.ask,
        "close": quote.close,
        "volume": quote.volume,
        "age_ms": max(0.0, quote.age_ms()),
        "timestamp": quote.timestamp.isoformat(),
        "source": quote.source,
    }


def write_report(report_dir: Path, report: Dict[str, Any]) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / (
        "pool_strategy_module_"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + ".json"
    )
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_dashboard(output: Path, report: Dict[str, Any]) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_dashboard_html(report), encoding="utf-8")
    return output


def elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


if __name__ == "__main__":
    raise SystemExit(main())
