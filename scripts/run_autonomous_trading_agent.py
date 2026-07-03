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

from trading.config import Settings
from trading.ibkr_readonly import ParallelIbkrReadOnlyQuoteSource
from trading.market_data import Quote
from trading.strategy import ValueFilterConfig, ValuePoolFilter
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
    errors: List[str]

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
            "errors": self.errors,
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
    state: Dict[str, Dict[str, float]] = {}
    args.report_dir.mkdir(parents=True, exist_ok=True)
    args.candidate_inbox.mkdir(parents=True, exist_ok=True)
    cycle = 0
    while args.cycles <= 0 or cycle < args.cycles:
        cycle += 1
        started = time.perf_counter()
        result = run_cycle(args, api_key, settings, state, cycle)
        append_jsonl(args.report_dir / "cycles.jsonl", result.as_dict())
        write_json(args.report_dir / "latest.json", result.as_dict())
        elapsed = time.perf_counter() - started
        if args.cycles > 0 and cycle >= args.cycles:
            break
        time.sleep(max(0.0, args.cycle_seconds - elapsed))
    return 0


def run_cycle(
    args: argparse.Namespace,
    api_key: str,
    settings: Settings,
    state: Dict[str, Dict[str, float]],
    cycle: int,
) -> AgentCycle:
    errors: List[str] = []
    strategy_run = None
    health = request_json("GET", "/health", None, api_url=args.api_url, api_key=api_key, timeout=10.0)
    lock_state = str(health.get("lock_state", "unknown"))
    tws = health.get("tws", {}) if isinstance(health.get("tws"), dict) else {}
    ready_for_orders = tws.get("ready_for_orders") is True
    allowed_symbols = sorted(set(health.get("limits", {}).get("allowed_symbols", [])))
    monitor_symbols, module_allowed = select_monitor_symbols(args, allowed_symbols)
    quotes = fetch_quotes(args, settings, monitor_symbols, cycle, errors)
    top_movers = update_market_state(state, quotes)
    research_tasks = build_research_tasks(top_movers, module_allowed)
    write_json(args.report_dir / "research_tasks.json", {"tasks": research_tasks, "created_at": utc_now()})
    process_candidate_inbox(args, errors)

    should_run_strategy = (
        not args.disable_strategy
        and ready_for_orders
        and lock_state == "TRADE_LOCK"
        and args.strategy_every_cycles > 0
        and cycle % args.strategy_every_cycles == 0
    )
    if should_run_strategy:
        strategy_run = run_strategy_once(args, api_key, monitor_symbols)
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
        errors=errors,
    )


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
    source = ParallelIbkrReadOnlyQuoteSource(
        host=settings.tws_host,
        port=settings.tws_port,
        client_id=args.client_id + cycle * 100,
        timeout=args.quote_timeout,
        snapshot=True,
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
    started = time.perf_counter()
    result = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=120)
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


if __name__ == "__main__":
    raise SystemExit(main())
