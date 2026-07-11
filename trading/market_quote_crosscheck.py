"""Cross-validate market session expectations against received quotes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from trading.config import PROJECT_ROOT
from trading.market_session import write_market_session_report
from trading.paper_audit_db import insert_event


REPORT_DIR = PROJECT_ROOT / "reports" / "market_quote_crosscheck"
ACTIVE_SESSIONS = {"PREMARKET", "REGULAR", "AFTERHOURS", "EARLY_CLOSE"}
CLOSED_SESSIONS = {"CLOSED", "WEEKEND", "HOLIDAY"}


def build_market_quote_crosscheck_report(
    *,
    cycle_id: str,
    symbols: Sequence[str],
    market_session: Mapping[str, Any] | None = None,
    streaming_diagnostics: Mapping[str, Any] | None = None,
    write_sqlite: bool = True,
) -> dict[str, Any]:
    market_session = dict(market_session or write_market_session_report(symbols=symbols))
    streaming_diagnostics = dict(streaming_diagnostics or _read_json(PROJECT_ROOT / "reports" / "streaming_quote_diagnostics" / "latest.json"))
    rows_by_symbol = {
        str(row.get("symbol", "")).upper(): row
        for row in streaming_diagnostics.get("rows", [])
        if isinstance(row, Mapping)
    }
    session_state = str(market_session.get("session_state") or "UNKNOWN")
    expected = bool(market_session.get("expected_live_bid_ask"))
    now = _now()
    rows = []
    for symbol in [item.strip().upper() for item in symbols if item and item.strip()]:
        diag = rows_by_symbol.get(symbol, {})
        row = crosscheck_row(
            timestamp=now,
            cycle_id=cycle_id,
            symbol=symbol,
            session_state=session_state,
            expected_live_bid_ask=expected,
            quote=diag,
        )
        rows.append(row)
        if write_sqlite:
            insert_event(
                "market_quote_crosscheck_events",
                {
                    "timestamp": row["timestamp"],
                    "cycle_id": cycle_id,
                    "symbol": symbol,
                    "market_session_state": session_state,
                    "quote_blocked_reason": row["quote_blocked_reason"],
                    "cross_validation_result": row["cross_validation_result"],
                    "payload_json": json.dumps(row, sort_keys=True),
                },
            )
            insert_event(
                "quote_readiness_events",
                {
                    "timestamp": row["timestamp"],
                    "cycle_id": cycle_id,
                    "symbol": symbol,
                    "quote_use_case": "EXECUTION_GATE",
                    "execution_allowed": int(row["cross_validation_result"] == "live_quote_ok"),
                    "blocked_reason": row["execution_blocked_reason"],
                    "payload_json": json.dumps(row, sort_keys=True),
                },
            )
    if not rows and not symbols:
        row = crosscheck_row(
            timestamp=now,
            cycle_id=cycle_id,
            symbol="",
            session_state=session_state,
            expected_live_bid_ask=expected,
            quote={},
        )
        rows.append(row)
    report = {
        "timestamp": now,
        "cycle_id": cycle_id,
        "source": "market_quote_crosscheck",
        "market_session_state": session_state,
        "expected_live_bid_ask": expected,
        "rows": rows,
        "summary": summarize(rows),
        "orders_submitted": 0,
        "orders_cancelled": 0,
        "regulatory_snapshot_used": False,
        "paid_snapshot_used": False,
    }
    write_report(report)
    return report


def crosscheck_row(
    *,
    timestamp: str,
    cycle_id: str,
    symbol: str,
    session_state: str,
    expected_live_bid_ask: bool,
    quote: Mapping[str, Any],
) -> dict[str, Any]:
    bid_received = bool(quote.get("bid_received") or quote.get("bid") is not None)
    ask_received = bool(quote.get("ask_received") or quote.get("ask") is not None)
    last_received = bool(quote.get("last_received") or quote.get("last") is not None)
    live_data_confirmed = bool(quote.get("live_data_confirmed"))
    blocked_reason = str(quote.get("blocked_reason") or "")
    result = classify_cross_validation_result(
        session_state=session_state,
        expected_live_bid_ask=expected_live_bid_ask,
        bid_received=bid_received,
        ask_received=ask_received,
        last_received=last_received,
        live_data_confirmed=live_data_confirmed,
        quote_blocked_reason=blocked_reason,
    )
    execution_blocked = result != "live_quote_ok"
    execution_blocked_reason = ""
    if session_state in CLOSED_SESSIONS:
        execution_blocked_reason = "market_closed_no_live_bid_ask_expected"
    elif execution_blocked:
        execution_blocked_reason = blocked_reason or result
    return {
        "timestamp": timestamp,
        "cycle_id": cycle_id,
        "symbol": symbol,
        "market_session_state": session_state,
        "expected_live_bid_ask": expected_live_bid_ask,
        "bid_received": bid_received,
        "ask_received": ask_received,
        "last_received": last_received,
        "live_data_confirmed": live_data_confirmed,
        "quote_blocked_reason": blocked_reason,
        "cross_validation_result": result,
        "execution_blocked": execution_blocked,
        "execution_blocked_reason": execution_blocked_reason,
    }


def classify_cross_validation_result(
    *,
    session_state: str,
    expected_live_bid_ask: bool,
    bid_received: bool,
    ask_received: bool,
    last_received: bool,
    live_data_confirmed: bool,
    quote_blocked_reason: str,
) -> str:
    reason = quote_blocked_reason.lower()
    if session_state in CLOSED_SESSIONS:
        return "normal_market_closed"
    if session_state == "UNKNOWN":
        return "unknown"
    if session_state not in ACTIVE_SESSIONS and not expected_live_bid_ask:
        return "normal_outside_session"
    if live_data_confirmed and bid_received and ask_received:
        return "live_quote_ok"
    if "subscription" in reason or "permission" in reason or "market data" in reason:
        return "subscription_problem"
    if "connected" in reason or "tws" in reason or "handshake" in reason:
        return "TWS_problem"
    if "contract" in reason:
        return "contract_problem"
    if expected_live_bid_ask and (not bid_received or not ask_received):
        return "quote_feed_problem"
    if last_received and not bid_received and not ask_received:
        return "normal_outside_session"
    return "unknown"


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for row in rows:
        result = str(row.get("cross_validation_result") or "unknown")
        counts[result] = counts.get(result, 0) + 1
    return {
        "row_count": len(rows),
        "result_counts": counts,
        "execution_ready_symbols": [row.get("symbol") for row in rows if row.get("cross_validation_result") == "live_quote_ok"],
        "blocked_symbols": [
            {
                "symbol": row.get("symbol"),
                "reason": row.get("execution_blocked_reason"),
                "cross_validation_result": row.get("cross_validation_result"),
            }
            for row in rows
            if row.get("execution_blocked")
        ],
    }


def write_report(report: Mapping[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "latest.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    (REPORT_DIR / "latest.md").write_text(_markdown(report), encoding="utf-8")


def _markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Market Quote Crosscheck",
        "",
        f"- timestamp: {report.get('timestamp')}",
        f"- cycle_id: {report.get('cycle_id')}",
        f"- market_session_state: {report.get('market_session_state')}",
        f"- expected_live_bid_ask: {report.get('expected_live_bid_ask')}",
        f"- orders_submitted: {report.get('orders_submitted')}",
        "",
        "| Symbol | Bid | Ask | Last | Live | Result | Blocked Reason |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    for row in report.get("rows", []):
        if isinstance(row, Mapping):
            lines.append(
                f"| {row.get('symbol')} | {row.get('bid_received')} | {row.get('ask_received')} | "
                f"{row.get('last_received')} | {row.get('live_data_confirmed')} | "
                f"{row.get('cross_validation_result')} | {row.get('execution_blocked_reason')} |"
            )
    return "\n".join(lines) + "\n"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
