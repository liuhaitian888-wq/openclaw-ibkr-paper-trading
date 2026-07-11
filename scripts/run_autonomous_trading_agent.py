"""Run the autonomous paper trading supervisor loop.

The supervisor keeps working after TRADE_LOCK is enabled: it refreshes the
universe, requests live IBKR quotes for the full monitor pool, records market
state, emits research tasks, processes approved candidate drafts, and triggers
the strategy module on a schedule.

It does not bypass the Python hard gates. Any order still goes through the
Trading API risk, lock, token, TWS readiness, and audit checks.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.account_state_manager import build_account_state
from trading.config import Settings
from trading.event_risk_control import build_event_risk_report
from trading.event_router import build_event_router_report
from trading.gap_escape_manager import build_gap_escape_report
from trading.gap_risk_manager import build_gap_risk_report
from trading.ibkr_readonly import ParallelIbkrReadOnlyQuoteSource
from trading.ibkr_streaming import IbkrStreamingQuoteSource
from trading.market_data import Quote
from trading.options_hedge_planner import build_options_hedge_report
from trading.pool_manager import build_pool_manager_report
from trading.position_guard import build_position_guard_report
from trading.position_protection import run_position_protection
from trading.process_guard import ExecutionLock, stop_duplicate_autonomous_processes
from trading.profit_lock import build_profit_lock_report
from trading.strategy import ValueFilterConfig, ValuePoolFilter
from trading.take_profit import build_take_profit_report
from trading.trailing_profit import build_trailing_profit_report
from trading.universe import (
    DEFAULT_UNIVERSE_FILE,
    UniverseSelectionConfig,
    load_universe,
    select_universe,
)


DEFAULT_API_URL = "http://192.168.64.1:8787"


@dataclass(frozen=True)
class AgentCycle:
    cycle: int
    created_at: str
    lock_state: str
    ready_for_orders: bool
    monitor_symbols: List[str]
    module_allowed_symbols: List[str]
    quote_count: int
    top_movers: List[Dict[str, object]]
    research_tasks: List[Dict[str, object]]
    strategy_run: Optional[Dict[str, object]]
    streaming_enabled: bool
    streaming_symbols: List[str]
    streaming_quote_count: int
    streaming_stale_symbols: List[str]
    streaming_errors: List[str]
    streaming_quotes: Dict[str, Dict[str, object]]
    errors: List[str]
    timings: Dict[str, float]
    account_state_manager: Dict[str, object]
    position_guard: Dict[str, object]
    pool_manager: Dict[str, object]
    event_risk: Dict[str, object]
    gap_risk: Dict[str, object]
    position_protection: Dict[str, object]
    gap_escape: Dict[str, object]
    event_router: Dict[str, object]
    profit_lock: Dict[str, object]
    take_profit: Dict[str, object]
    trailing_profit: Dict[str, object]
    options_hedge: Dict[str, object]
    mode9_buy_freeze: bool

    def as_dict(self) -> Dict[str, object]:
        return {
            "cycle": self.cycle,
            "created_at": self.created_at,
            "lock_state": self.lock_state,
            "ready_for_orders": self.ready_for_orders,
            "monitor_symbols": self.monitor_symbols,
            "module_allowed_symbols": self.module_allowed_symbols,
            "quote_count": self.quote_count,
            "top_movers": self.top_movers,
            "research_tasks": self.research_tasks,
            "strategy_run": self.strategy_run,
            "streaming_enabled": self.streaming_enabled,
            "streaming_symbols": self.streaming_symbols,
            "streaming_quote_count": self.streaming_quote_count,
            "streaming_stale_symbols": self.streaming_stale_symbols,
            "streaming_errors": self.streaming_errors,
            "streaming_quotes": self.streaming_quotes,
            "errors": self.errors,
            "timings": self.timings,
            "account_state_manager": self.account_state_manager,
            "position_guard": self.position_guard,
            "pool_manager": self.pool_manager,
            "event_risk": self.event_risk,
            "gap_risk": self.gap_risk,
            "position_protection": self.position_protection,
            "gap_escape": self.gap_escape,
            "event_router": self.event_router,
            "profit_lock": self.profit_lock,
            "take_profit": self.take_profit,
            "trailing_profit": self.trailing_profit,
            "options_hedge": self.options_hedge,
            "mode9_buy_freeze": self.mode9_buy_freeze,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--api-key-file", type=Path, default=PROJECT_ROOT / ".secrets" / "openclaw_api_key")
    parser.add_argument("--universe-file", type=Path, default=DEFAULT_UNIVERSE_FILE)
    parser.add_argument("--max-universe-symbols", type=int, default=60)
    parser.add_argument("--min-value-score", type=float, default=45.0)
    parser.add_argument("--cycle-seconds", type=float, default=30.0)
    parser.add_argument("--cycles", type=int, default=0, help="0 means run forever")
    parser.add_argument("--strategy-every-cycles", type=int, default=2)
    parser.add_argument("--strategy-mode", choices=("validate", "stage", "paper"), default="paper")
    parser.add_argument("--strategy-steps", type=int, default=1)
    parser.add_argument("--strategy-max-orders", type=int, default=4)
    parser.add_argument("--client-id", type=int, default=5200)
    parser.add_argument("--ibkr-workers", type=int, default=8)
    parser.add_argument("--ibkr-symbols-per-worker", type=int, default=8)
    parser.add_argument("--quote-timeout", type=float, default=8.0)
    parser.add_argument("--market-data-type", type=int, default=1)
    parser.add_argument("--exchange", default="SMART")
    parser.add_argument("--report-dir", type=Path, default=PROJECT_ROOT / "reports" / "autonomous_agent")
    parser.add_argument("--candidate-inbox", type=Path, default=PROJECT_ROOT / "reports" / "agent_research" / "inbox")
    parser.add_argument("--candidate-auto-approve", action="store_true")
    parser.add_argument("--disable-strategy", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = read_required(args.api_key_file, "OPENCLAW_API_KEY")
    settings = Settings.load()
    can_submit_orders = args.strategy_mode in {"paper", "stage"} and not args.disable_strategy
    stop_duplicate_autonomous_processes(keep_pid=os.getpid())
    state: Dict[str, Dict[str, float]] = {}
    streaming_source = build_streaming_source(settings)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    args.candidate_inbox.mkdir(parents=True, exist_ok=True)
    cycle = 0
    with ExecutionLock(
        process_name="mode9_autonomous_agent",
        mode=args.strategy_mode,
        can_submit_orders=can_submit_orders,
        prefer_mode9=True,
    ) as execution_lock:
        try:
            while args.cycles <= 0 or cycle < args.cycles:
                cycle += 1
                execution_lock.heartbeat()
                started = time.perf_counter()
                try:
                    result = run_cycle(args, api_key, settings, state, cycle, streaming_source)
                except Exception as exc:
                    result = failed_cycle(cycle, exc, started)
                append_jsonl(args.report_dir / "cycles.jsonl", result.as_dict())
                write_json(args.report_dir / "latest.json", result.as_dict())
                elapsed = time.perf_counter() - started
                if args.cycles > 0 and cycle >= args.cycles:
                    break
                time.sleep(max(0.0, args.cycle_seconds - elapsed))
        finally:
            if streaming_source is not None:
                streaming_source.stop()
    return 0


def run_cycle(
    args: argparse.Namespace,
    api_key: str,
    settings: Settings,
    state: Dict[str, Dict[str, float]],
    cycle: int,
    streaming_source: Optional[IbkrStreamingQuoteSource] = None,
) -> AgentCycle:
    cycle_started = time.perf_counter()
    errors: List[str] = []
    timings: Dict[str, float] = {}
    strategy_run = None
    buy_freeze = mode9_buy_freeze()
    started = time.perf_counter()
    health = request_json("GET", "/health", None, api_url=args.api_url, api_key=api_key, timeout=10.0)
    timings["health_ms"] = elapsed_ms(started)
    lock_state = str(health.get("lock_state", "unknown"))
    tws = health.get("tws", {}) if isinstance(health.get("tws"), dict) else {}
    ready_for_orders = tws.get("ready_for_orders") is True
    allowed_symbols = sorted(set(health.get("limits", {}).get("allowed_symbols", [])))
    started = time.perf_counter()
    try:
        account_state = build_account_state(settings=settings, force_refresh=False)
        account_state_manager = {
            "source": "account_state_manager",
            "timestamp": account_state.timestamp,
            "used_cached_state": account_state.used_cached_state,
            "force_refresh_required": account_state.force_refresh.force_refresh_required if account_state.force_refresh else None,
            "force_refresh_performed": account_state.force_refresh.force_refresh_performed if account_state.force_refresh else None,
            "force_refresh_ok": account_state.force_refresh.force_refresh_ok if account_state.force_refresh else None,
            "state_stale": account_state.state_stale,
            "blocked_reason": account_state.blocked_reason,
            "position_count": len(account_state.positions),
            "open_order_count": len(account_state.open_orders),
        }
    except Exception as exc:
        account_state_manager = {"status": "error", "error": str(exc)}
        errors.append(f"account state manager failed: {exc}")
    timings["account_state_manager_ms"] = elapsed_ms(started)
    started = time.perf_counter()
    try:
        position_guard = build_position_guard_report(settings=settings)
    except Exception as exc:
        position_guard = {"status": "error", "error": str(exc), "symbols": []}
        errors.append(f"position guard failed: {exc}")
    timings["position_guard_ms"] = elapsed_ms(started)
    started = time.perf_counter()
    try:
        pool_manager = build_pool_manager_report(position_guard=position_guard, universe_file=args.universe_file)
    except Exception as exc:
        pool_manager = {"status": "error", "error": str(exc), "layers": []}
        errors.append(f"pool manager failed: {exc}")
    timings["pool_manager_ms"] = elapsed_ms(started)
    started = time.perf_counter()
    try:
        event_risk = build_event_risk_report(position_guard=position_guard)
    except Exception as exc:
        event_risk = {"status": "error", "error": str(exc), "symbols": []}
        errors.append(f"event risk failed: {exc}")
    timings["event_risk_ms"] = elapsed_ms(started)
    started = time.perf_counter()
    try:
        gap_risk = build_gap_risk_report(position_guard=position_guard, event_risk_report=event_risk)
    except Exception as exc:
        gap_risk = {"status": "error", "error": str(exc), "symbols": []}
        errors.append(f"gap risk failed: {exc}")
    timings["gap_risk_ms"] = elapsed_ms(started)
    started = time.perf_counter()
    try:
        position_protection = run_position_protection(settings=settings, guard_report=position_guard)
    except Exception as exc:
        position_protection = {"status": "error", "error": str(exc), "records": []}
        errors.append(f"position protection failed: {exc}")
    timings["position_protection_ms"] = elapsed_ms(started)
    started = time.perf_counter()
    try:
        gap_escape = build_gap_escape_report(
            position_guard=position_guard,
            gap_risk_report=gap_risk,
            event_risk_report=event_risk,
            settings=settings,
        )
    except Exception as exc:
        gap_escape = {"status": "error", "error": str(exc), "symbols": []}
        errors.append(f"gap escape failed: {exc}")
    timings["gap_escape_ms"] = elapsed_ms(started)
    started = time.perf_counter()
    try:
        event_router = build_event_router_report(
            position_guard=position_guard,
            gap_risk=gap_risk,
            gap_escape=gap_escape,
            event_risk=event_risk,
            pool_membership=pool_manager.get("membership") if isinstance(pool_manager, dict) else None,
        )
    except Exception as exc:
        event_router = {"status": "error", "error": str(exc), "actions": []}
        errors.append(f"event router failed: {exc}")
    timings["event_router_ms"] = elapsed_ms(started)
    started = time.perf_counter()
    try:
        profit_lock = build_profit_lock_report(position_guard=position_guard)
    except Exception as exc:
        profit_lock = {"status": "error", "error": str(exc), "symbols": []}
        errors.append(f"profit lock failed: {exc}")
    timings["profit_lock_ms"] = elapsed_ms(started)
    started = time.perf_counter()
    try:
        take_profit = build_take_profit_report(position_guard=position_guard)
    except Exception as exc:
        take_profit = {"status": "error", "error": str(exc), "symbols": []}
        errors.append(f"take profit failed: {exc}")
    timings["take_profit_ms"] = elapsed_ms(started)
    started = time.perf_counter()
    try:
        trailing_profit = build_trailing_profit_report(position_guard=position_guard)
    except Exception as exc:
        trailing_profit = {"status": "error", "error": str(exc), "symbols": []}
        errors.append(f"trailing profit failed: {exc}")
    timings["trailing_profit_ms"] = elapsed_ms(started)
    started = time.perf_counter()
    try:
        options_hedge = build_options_hedge_report(
            position_guard=position_guard,
            event_risk_report=event_risk,
            settings=settings,
        )
    except Exception as exc:
        options_hedge = {"status": "error", "error": str(exc), "symbols": []}
        errors.append(f"options hedge failed: {exc}")
    timings["options_hedge_ms"] = elapsed_ms(started)
    started = time.perf_counter()
    monitor_symbols, module_allowed = select_monitor_symbols(args, allowed_symbols)
    held_symbols = [
        str(item.get("symbol", "")).upper()
        for item in position_guard.get("symbols", [])
        if float(item.get("position_qty") or 0) > 0
    ]
    monitor_symbols = list(dict.fromkeys([*held_symbols, *monitor_symbols]))
    timings["select_universe_ms"] = elapsed_ms(started)
    started = time.perf_counter()
    quotes = fetch_quotes(args, settings, monitor_symbols, cycle, errors)
    timings["fetch_quotes_ms"] = elapsed_ms(started)
    started = time.perf_counter()
    top_movers = update_market_state(state, quotes)
    timings["update_market_state_ms"] = elapsed_ms(started)
    started = time.perf_counter()
    research_tasks = build_research_tasks(top_movers, module_allowed)
    timings["build_research_tasks_ms"] = elapsed_ms(started)
    started = time.perf_counter()
    write_json(args.report_dir / "research_tasks.json", {"tasks": research_tasks, "created_at": utc_now()})
    timings["write_research_tasks_ms"] = elapsed_ms(started)
    started = time.perf_counter()
    process_candidate_inbox(args, errors)
    timings["process_candidate_inbox_ms"] = elapsed_ms(started)

    started = time.perf_counter()
    should_run_strategy = (
        not args.disable_strategy
        and ready_for_orders
        and lock_state == "TRADE_LOCK"
        and args.strategy_every_cycles > 0
        and cycle % args.strategy_every_cycles == 0
    )
    if should_run_strategy:
        strategy_run = run_strategy_once(args, api_key, monitor_symbols, buy_freeze=buy_freeze)
    timings["strategy_run_ms"] = elapsed_ms(started)
    streaming_report = streaming_report_payload(streaming_source)
    timings["cycle_total_ms"] = elapsed_ms(cycle_started)
    return AgentCycle(
        cycle=cycle,
        created_at=utc_now(),
        lock_state=lock_state,
        ready_for_orders=ready_for_orders,
        monitor_symbols=monitor_symbols,
        module_allowed_symbols=module_allowed,
        quote_count=len(quotes),
        top_movers=top_movers,
        research_tasks=research_tasks,
        strategy_run=strategy_run,
        streaming_enabled=streaming_source is not None,
        streaming_symbols=list(streaming_report["streaming_symbols"]),
        streaming_quote_count=int(streaming_report["streaming_quote_count"]),
        streaming_stale_symbols=list(streaming_report["streaming_stale_symbols"]),
        streaming_errors=list(streaming_report["streaming_errors"]),
        streaming_quotes=dict(streaming_report["streaming_quotes"]),
        errors=errors,
        timings=timings,
        account_state_manager=dict(account_state_manager),
        position_guard=dict(position_guard),
        pool_manager=dict(pool_manager),
        event_risk=dict(event_risk),
        gap_risk=dict(gap_risk),
        position_protection=dict(position_protection),
        gap_escape=dict(gap_escape),
        event_router=dict(event_router),
        profit_lock=dict(profit_lock),
        take_profit=dict(take_profit),
        trailing_profit=dict(trailing_profit),
        options_hedge=dict(options_hedge),
        mode9_buy_freeze=buy_freeze,
    )


def failed_cycle(cycle: int, exc: Exception, started: float) -> AgentCycle:
    return AgentCycle(
        cycle=cycle,
        created_at=utc_now(),
        lock_state="unknown",
        ready_for_orders=False,
        monitor_symbols=[],
        module_allowed_symbols=[],
        quote_count=0,
        top_movers=[],
        research_tasks=[],
        strategy_run=None,
        streaming_enabled=False,
        streaming_symbols=[],
        streaming_quote_count=0,
        streaming_stale_symbols=[],
        streaming_errors=[],
        streaming_quotes={},
        errors=[f"cycle failed: {exc}"],
        timings={"cycle_total_ms": elapsed_ms(started)},
        account_state_manager={},
        position_guard={},
        pool_manager={},
        event_risk={},
        gap_risk={},
        position_protection={},
        gap_escape={},
        event_router={},
        profit_lock={},
        take_profit={},
        trailing_profit={},
        options_hedge={},
        mode9_buy_freeze=mode9_buy_freeze(),
    )


def build_streaming_source(settings: Settings) -> Optional[IbkrStreamingQuoteSource]:
    if not settings.streaming_market_data_enabled:
        return None
    source = IbkrStreamingQuoteSource(
        symbols=settings.streaming_symbols,
        host=settings.streaming_tws_host,
        port=settings.streaming_tws_port,
        client_id=settings.streaming_client_id,
        stale_ms=settings.streaming_stale_ms,
        max_symbols=settings.streaming_max_symbols,
        market_data_type=1,
    )
    source.start(timeout=settings.tws_status_timeout)
    return source


def streaming_report_payload(
    streaming_source: Optional[IbkrStreamingQuoteSource],
) -> Dict[str, object]:
    if streaming_source is None:
        return {
            "streaming_symbols": [],
            "streaming_quote_count": 0,
            "streaming_stale_symbols": [],
            "streaming_errors": [],
            "streaming_quotes": {},
        }
    return streaming_source.report()


def select_monitor_symbols(args: argparse.Namespace, allowed_symbols: List[str]) -> tuple[List[str], List[str]]:
    value_filter = ValuePoolFilter(ValueFilterConfig(min_score=args.min_value_score))
    selection = select_universe(
        load_universe(args.universe_file),
        value_filter,
        UniverseSelectionConfig(max_symbols=args.max_universe_symbols),
        gateway_allowed_symbols=allowed_symbols or None,
    )
    monitor = []
    structural_reasons = {
        "disabled in universe",
        "not in gateway allowlist",
        "missing required tag",
        "excluded tag",
        "sector not included",
        "sector excluded",
    }
    for record in selection.records:
        reasons = {str(reason) for reason in record.get("reasons", [])}
        if reasons.intersection(structural_reasons):
            continue
        monitor.append(str(record["symbol"]))
        if args.max_universe_symbols > 0 and len(monitor) >= args.max_universe_symbols:
            break
    return monitor, selection.symbols


def fetch_quotes(
    args: argparse.Namespace,
    settings: Settings,
    symbols: List[str],
    cycle: int,
    errors: List[str],
) -> List[Quote]:
    if not symbols:
        return []
    if env_bool("NO_PAID_MARKET_DATA_REQUESTS", True) and not env_bool("ALLOW_SNAPSHOT_MARKET_DATA", False):
        errors.append("automatic snapshot market data blocked; using streaming report/cache only")
        return []
    source = ParallelIbkrReadOnlyQuoteSource(
        host=settings.tws_host,
        port=settings.tws_port,
        client_id=args.client_id + cycle * 100,
        timeout=args.quote_timeout,
        snapshot=env_bool("ALLOW_SNAPSHOT_MARKET_DATA", False),
        market_data_type=args.market_data_type,
        exchange=args.exchange,
        workers=args.ibkr_workers,
        symbols_per_worker=args.ibkr_symbols_per_worker,
    )
    quotes = source.get_quotes(symbols)
    errors.extend(source.last_errors)
    return quotes


def update_market_state(
    state: Dict[str, Dict[str, float]],
    quotes: List[Quote],
) -> List[Dict[str, object]]:
    movers = []
    for quote in quotes:
        symbol = quote.symbol.upper()
        previous = state.get(symbol, {}).get("last")
        step_return = 0.0 if previous in {None, 0.0} else (quote.last - previous) / previous
        spread_pct = None if quote.spread is None or quote.last <= 0 else quote.spread / quote.last
        state[symbol] = {"last": quote.last, "timestamp": quote.timestamp.timestamp()}
        movers.append(
            {
                "symbol": symbol,
                "last": quote.last,
                "step_return": round(step_return, 6),
                "spread_pct": None if spread_pct is None else round(spread_pct, 6),
                "volume": quote.volume,
                "age_ms": quote.age_ms(),
            }
        )
    return sorted(movers, key=lambda item: abs(float(item["step_return"])), reverse=True)[:12]


def build_research_tasks(
    top_movers: List[Dict[str, object]],
    module_allowed: List[str],
) -> List[Dict[str, object]]:
    allowed = set(module_allowed)
    tasks = []
    for mover in top_movers[:8]:
        symbol = str(mover["symbol"])
        tasks.append(
            {
                "symbol": symbol,
                "priority": "high" if symbol in allowed else "watch",
                "reason": "large intracycle move or spread/volume change",
                "requested_checks": [
                    "latest company news",
                    "SEC filings and earnings calendar",
                    "fundamental profile refresh",
                    "bear-case falsification",
                ],
            }
        )
    return tasks


def process_candidate_inbox(args: argparse.Namespace, errors: List[str]) -> None:
    for path in sorted(args.candidate_inbox.glob("*.json")):
        review_cmd = [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "review_candidate_report.py"),
            str(path),
            "--universe-file",
            str(args.universe_file),
        ]
        try:
            review = subprocess.run(review_cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=60)
        except Exception as exc:
            errors.append(f"candidate review failed for {path.name}: {exc}")
            continue
        if review.returncode not in {0, 2}:
            errors.append(f"candidate review command failed for {path.name}: {review.stderr.strip()}")
            continue
        try:
            payload = json.loads(review.stdout)
        except json.JSONDecodeError:
            errors.append(f"candidate review produced non-JSON output for {path.name}")
            continue
        report_path = payload.get("report_path")
        if args.candidate_auto_approve and payload.get("hard_audit", {}).get("approved") is True and isinstance(report_path, str):
            approve_cmd = [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "approve_candidate_to_universe.py"),
                report_path,
                "--universe-file",
                str(args.universe_file),
                "--approved-by",
                "autonomous-agent",
            ]
            approve = subprocess.run(approve_cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30)
            if approve.returncode != 0:
                errors.append(f"candidate approval failed for {path.name}: {approve.stderr.strip()}")


def run_strategy_once(
    args: argparse.Namespace,
    api_key: str,
    monitor_symbols: List[str],
    *,
    buy_freeze: bool,
) -> Dict[str, object]:
    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "run_pool_strategy_module.py"),
        "--mode",
        args.strategy_mode,
        "--source",
        "ibkr-readonly",
        "--universe-file",
        str(args.universe_file),
        "--symbols",
        ",".join(monitor_symbols),
        "--max-universe-symbols",
        str(args.max_universe_symbols),
        "--min-value-score",
        str(args.min_value_score),
        "--steps",
        str(args.strategy_steps),
        "--full-pool-each-step",
        "--max-orders",
        str(args.strategy_max_orders),
        "--api-url",
        args.api_url,
        "--api-key-file",
        str(args.api_key_file),
        "--market-data-type",
        str(args.market_data_type),
        "--exchange",
        args.exchange,
        "--ibkr-workers",
        str(args.ibkr_workers),
        "--ibkr-symbols-per-worker",
        str(args.ibkr_symbols_per_worker),
        "--quote-timeout",
        str(args.quote_timeout),
    ]
    if buy_freeze:
        command.append("--buy-freeze")
    started = time.perf_counter()
    env = os.environ.copy()
    env["OPENCLAW_EXECUTION_LOCK_OWNER_PID"] = str(os.getpid())
    result = subprocess.run(command, cwd=PROJECT_ROOT, env=env, capture_output=True, text=True, timeout=120)
    payload: Dict[str, object] = {
        "returncode": result.returncode,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
    }
    try:
        parsed = json.loads(result.stdout)
        payload["submitted_count"] = parsed.get("submitted_count")
        payload["report_path"] = parsed.get("report_path")
        payload["dashboard_path"] = parsed.get("dashboard_path")
        payload["returned_symbols"] = parsed.get("returned_symbols")
    except json.JSONDecodeError:
        payload["stdout_tail"] = result.stdout[-1000:]
    if result.stderr:
        payload["stderr_tail"] = result.stderr[-1000:]
    return payload


def mode9_buy_freeze() -> bool:
    return os.getenv("MODE9_BUY_FREEZE", "true").strip().lower() in {"1", "true", "yes", "on"}


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


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
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
        if isinstance(data, dict):
            return data
    raise RuntimeError("Trading API returned non-object JSON")


def read_required(path: Path, name: str) -> str:
    value = path.expanduser().read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError(f"{name} file is empty: {path}")
    return value


def append_jsonl(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


if __name__ == "__main__":
    raise SystemExit(main())
