"""Generate a sanitized, read-only weekly Paper trading report."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def parse_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def query_one(con: sqlite3.Connection, sql: str, params: tuple[object, ...]) -> Any:
    try:
        row = con.execute(sql, params).fetchone()
    except sqlite3.OperationalError:
        return None
    return None if row is None else row[0]


def table_count(con: sqlite3.Connection, table: str, column: str, start: str, end: str) -> int:
    value = query_one(con, f"SELECT count(*) FROM {table} WHERE {column} >= ? AND {column} < ?", (start, end))
    return int(value or 0)


def lifecycle_summary(path: Path, start: datetime, end: datetime) -> dict[str, Any]:
    records: list[tuple[datetime, str]] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            timestamp = parse_time(row.get("created_at") or row.get("timestamp"))
            if timestamp and start <= timestamp < end:
                records.append((timestamp, str(row.get("lifecycle_state") or "UNKNOWN")))
    records.sort()
    counts = Counter(state for _, state in records)
    seconds: Counter[str] = Counter()
    for index, (timestamp, state) in enumerate(records):
        next_time = records[index + 1][0] if index + 1 < len(records) else min(end, timestamp)
        seconds[state] += max(0, int((next_time - timestamp).total_seconds()))
    return {
        "samples": len(records),
        "state_counts": dict(sorted(counts.items())),
        "safe_mode_seconds": seconds.get("SAFE_MODE", 0),
        "paper_ready_seconds": seconds.get("PAPER_READY", 0),
        "last_state": records[-1][1] if records else "UNKNOWN",
    }


def collect_weekly_report(root: Path, db_path: Path, end: datetime) -> dict[str, Any]:
    end = end.astimezone(timezone.utc)
    start = end - timedelta(days=7)
    start_text, end_text = start.isoformat(), end.isoformat()
    database_available = db_path.exists()
    metrics: dict[str, Any] = {
        "strategy_decisions": 0,
        "signals": 0,
        "order_intents": 0,
        "risk_checks": 0,
        "orders_requested": 0,
        "broker_orders_seen": 0,
        "partial_fills": 0,
        "filled_orders": 0,
        "executions": 0,
        "commissions": 0,
        "risk_rejections": 0,
        "ibkr_errors": 0,
        "quote_blocks": 0,
        "scanner_runs": 0,
        "scanner_candidates": 0,
        "daily_pnl": None,
        "realized_pnl": None,
        "unrealized_pnl": None,
    }
    if database_available:
        uri = f"file:{db_path}?mode=ro&immutable=1"
        with sqlite3.connect(uri, uri=True) as con:
            metrics.update(
                signals=table_count(con, "strategy_signals", "timestamp_utc", start_text, end_text),
                strategy_decisions=table_count(con, "strategy_decisions", "timestamp", start_text, end_text),
                order_intents=table_count(con, "order_intent_events", "timestamp_utc", start_text, end_text),
                risk_checks=table_count(con, "risk_events", "timestamp", start_text, end_text),
                orders_requested=table_count(con, "order_requests", "created_at", start_text, end_text),
                broker_orders_seen=table_count(con, "broker_orders", "first_seen_at", start_text, end_text),
                partial_fills=int(query_one(con, "SELECT count(*) FROM broker_orders WHERE first_seen_at >= ? AND first_seen_at < ? AND filled > 0 AND remaining > 0", (start_text, end_text)) or 0),
                filled_orders=int(query_one(con, "SELECT count(*) FROM broker_orders WHERE first_seen_at >= ? AND first_seen_at < ? AND (completed = 1 OR upper(canonical_status) = 'FILLED' OR upper(status) = 'FILLED')", (start_text, end_text)) or 0),
                executions=table_count(con, "executions", "executed_at", start_text, end_text),
                commissions=table_count(con, "commission_events", "timestamp_utc", start_text, end_text),
                risk_rejections=int(query_one(con, "SELECT count(*) FROM risk_events WHERE timestamp >= ? AND timestamp < ? AND json_valid(payload_json) AND (json_extract(payload_json, '$.approved') = 0 OR json_extract(payload_json, '$.execution_allowed') = 0)", (start_text, end_text)) or 0),
                ibkr_errors=table_count(con, "ibkr_error_events", "timestamp_utc", start_text, end_text),
                quote_blocks=int(query_one(con, "SELECT count(*) FROM quote_readiness_events WHERE timestamp >= ? AND timestamp < ? AND execution_allowed = 0", (start_text, end_text)) or 0),
                scanner_runs=table_count(con, "ibkr_scanner_runs", "timestamp", start_text, end_text),
                scanner_candidates=int(query_one(con, "SELECT coalesce(sum(candidates_count), 0) FROM ibkr_scanner_runs WHERE timestamp >= ? AND timestamp < ?", (start_text, end_text)) or 0),
            )
            pnl = con.execute(
                "SELECT daily_pnl, realized_pnl, unrealized_pnl FROM daily_pnl_summary WHERE pnl_sample_time_utc >= ? AND pnl_sample_time_utc < ? ORDER BY pnl_sample_time_utc DESC LIMIT 1",
                (start_text, end_text),
            ).fetchone()
            if pnl:
                metrics["daily_pnl"], metrics["realized_pnl"], metrics["unrealized_pnl"] = pnl
            elif (payload_row := con.execute(
                "SELECT payload_json FROM pnl_state_events WHERE timestamp_utc >= ? AND timestamp_utc < ? AND stale_flag = 0 ORDER BY timestamp_utc DESC LIMIT 1",
                (start_text, end_text),
            ).fetchone()):
                try:
                    pnl_payload = json.loads(payload_row[0]).get("payload", {})
                except (TypeError, json.JSONDecodeError):
                    pnl_payload = {}
                metrics["daily_pnl"] = pnl_payload.get("daily_pnl")
                metrics["realized_pnl"] = pnl_payload.get("realized_pnl")
                metrics["unrealized_pnl"] = pnl_payload.get("unrealized_pnl")

    stream = read_json(root / "reports/streaming_quote_diagnostics/latest.json")
    stream_rows = stream.get("rows") if isinstance(stream.get("rows"), list) else []
    fresh_l1 = sum(bool(row.get("has_bid") and row.get("has_ask")) for row in stream_rows if isinstance(row, dict))
    scanner = read_json(root / "reports/ibkr_scanner/latest.json")
    account = read_json(root / "reports/account_state/latest.json")
    account_snapshot = account.get("account_snapshot") if isinstance(account.get("account_snapshot"), dict) else {}
    position_guard = read_json(root / "reports/position_guard/latest.json")
    positions = account.get("positions") if isinstance(account.get("positions"), list) else []
    if not positions and isinstance(position_guard.get("symbols"), list):
        positions = position_guard["symbols"]
    open_orders = account.get("open_orders") if isinstance(account.get("open_orders"), list) else []
    if not open_orders and isinstance(position_guard.get("open_orders"), list):
        open_orders = position_guard["open_orders"]
    lifecycle = lifecycle_summary(root / "reports/autonomous_agent/cycles.jsonl", start, end)
    blockers = []
    for source in (read_json(root / "reports/autonomous_agent/latest.json"), account, read_json(root / "reports/paper_execution_gate/latest.json")):
        reason = source.get("blocked_reason")
        if reason and str(reason) not in blockers:
            blockers.append(str(reason))
    return {
        "source": "weekly_trading_report",
        "report_only": True,
        "sensitive_values_included": False,
        "period": {"start_utc": start_text, "end_utc": end_text},
        "strategy_performance": {
            "decision_count": metrics["strategy_decisions"],
            "daily_pnl": metrics["daily_pnl"],
            "realized_pnl": metrics["realized_pnl"],
            "unrealized_pnl": metrics["unrealized_pnl"],
        },
        "orders_and_fills": {
            "signals": metrics["signals"],
            "strategy_decisions": metrics["strategy_decisions"],
            "order_intents": metrics["order_intents"],
            "risk_checks": metrics["risk_checks"],
            "requests": metrics["orders_requested"],
            "broker_orders_seen": metrics["broker_orders_seen"],
            "partial_fills": metrics["partial_fills"],
            "filled_orders": metrics["filled_orders"],
            "executions": metrics["executions"],
            "commissions": metrics["commissions"],
        },
        "risk_and_data_quality": {
            "risk_rejections": metrics["risk_rejections"],
            "quote_blocks": metrics["quote_blocks"],
            "ibkr_errors_or_disconnects": metrics["ibkr_errors"],
        },
        "lifecycle": lifecycle,
        "scanner_and_l1": {
            "scanner_runs": metrics["scanner_runs"],
            "scanner_candidates_total": metrics["scanner_candidates"],
            "latest_scanner_status": scanner.get("status"),
            "latest_scanner_candidate_count": scanner.get("candidate_count"),
            "l1_symbols_observed": len(stream_rows),
            "l1_symbols_with_fresh_bid_ask": fresh_l1,
            "l1_errors": len(stream.get("errors") or []),
        },
        "account_and_positions": {
            "mode": account.get("mode"),
            "state_stale": account.get("state_stale"),
            "snapshot": account_snapshot,
            "position_count": len(positions),
            "open_order_count": len(open_orders),
            "pnl_available": any(value is not None for value in (metrics["daily_pnl"], metrics["realized_pnl"], metrics["unrealized_pnl"])),
            "data_quality": account_snapshot.get("data_quality", {}),
        },
        "remaining_blockers": blockers,
        "database_available": database_available,
    }


def render_markdown(report: dict[str, Any]) -> str:
    performance = report["strategy_performance"]
    orders = report["orders_and_fills"]
    risk = report["risk_and_data_quality"]
    lifecycle = report["lifecycle"]
    coverage = report["scanner_and_l1"]
    account = report["account_and_positions"]
    blockers = report["remaining_blockers"]
    return f"""# Paper Trading Weekly Report

- Period: {report['period']['start_utc']} to {report['period']['end_utc']}
- Report only: true
- Sensitive values included: false

## Strategy and PnL

- Strategy decisions: {performance['decision_count']}
- Daily / realized / unrealized PnL: {performance['daily_pnl']} / {performance['realized_pnl']} / {performance['unrealized_pnl']}

## Orders, fills, and risk

- Signal -> decision -> intent -> risk -> submit -> ack -> partial -> fill -> execution -> commission: {orders['signals']} -> {orders['strategy_decisions']} -> {orders['order_intents']} -> {orders['risk_checks']} -> {orders['requests']} -> {orders['broker_orders_seen']} -> {orders['partial_fills']} -> {orders['filled_orders']} -> {orders['executions']} -> {orders['commissions']}
- Risk rejections / quote blocks: {risk['risk_rejections']} / {risk['quote_blocks']}
- IBKR errors or disconnects: {risk['ibkr_errors_or_disconnects']}

## Runtime and data quality

- SAFE_MODE seconds: {lifecycle['safe_mode_seconds']}
- PAPER_READY seconds: {lifecycle['paper_ready_seconds']}
- Last lifecycle state: {lifecycle['last_state']}
- Scanner runs / candidates: {coverage['scanner_runs']} / {coverage['scanner_candidates_total']}
- Latest scanner status: {coverage['latest_scanner_status']}
- L1 fresh bid/ask coverage: {coverage['l1_symbols_with_fresh_bid_ask']} / {coverage['l1_symbols_observed']}

## Account and positions

- Mode / stale: {account['mode']} / {account['state_stale']}
- Positions / open orders: {account['position_count']} / {account['open_order_count']}
- PnL available: {account['pnl_available']}
- Missing account fields: {(account.get('data_quality') or {}).get('missing_fields', [])}

## Remaining blockers

{chr(10).join(f'- {item}' for item in blockers) if blockers else '- None recorded'}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output_dir or root / "reports/weekly_trading"
    report = collect_weekly_report(root, args.database or root / "trading_audit.sqlite3", datetime.now(timezone.utc))
    output.mkdir(parents=True, exist_ok=True)
    week_key = report["period"]["end_utc"][:10]
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    markdown = render_markdown(report)
    for path, content in ((output / "latest.json", payload), (output / "latest.md", markdown), (output / f"week_ending_{week_key}.json", payload), (output / f"week_ending_{week_key}.md", markdown)):
        path.write_text(content, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
