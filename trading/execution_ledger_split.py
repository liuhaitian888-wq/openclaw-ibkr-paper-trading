"""Build split BUY/SELL intent ledgers and structured PnL reports."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from trading.config import PROJECT_ROOT
from trading.order_intents import OrderIntent, make_intent_id, utc_now
from trading.paper_audit_db import DB_PATH, ensure_paper_automation_tables, insert_event


EXECUTION_SPLIT_DIR = PROJECT_ROOT / "reports" / "execution_ledger_split"
PNL_LEDGER_DIR = PROJECT_ROOT / "reports" / "pnl_ledger"
SEPARATION_DIR = PROJECT_ROOT / "reports" / "buy_sell_separation"


def build_execution_and_pnl_ledgers(*, cycle_id: str | None = None) -> dict[str, Any]:
    ensure_paper_automation_tables()
    full = read_json(PROJECT_ROOT / "reports" / "full_paper_run" / "latest.json")
    cycle = cycle_id or str(full.get("cycle_id") or f"ledger-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
    intents = [
        *buy_intents(cycle),
        *protective_sell_intents(cycle),
        *gap_escape_intents(cycle),
        *profit_sell_intents(cycle),
        *event_risk_sell_intents(cycle),
        *options_plan_intents(cycle),
    ]
    pnl_report = build_pnl_ledger_report()
    persist_intents(intents)
    execution_report = execution_split_report(intents, pnl_report)
    separation_report = separation_report_payload(intents, pnl_report)
    write_reports(execution_report, pnl_report, separation_report)
    return {
        "execution_ledger_split": execution_report,
        "pnl_ledger": pnl_report,
        "buy_sell_separation": separation_report,
    }


def buy_intents(cycle_id: str) -> list[OrderIntent]:
    paper_buy = read_json(PROJECT_ROOT / "reports" / "paper_buy" / "latest.json")
    records = paper_buy.get("records", []) if isinstance(paper_buy.get("records"), list) else []
    intents = []
    for index, row in enumerate(records):
        if not isinstance(row, Mapping):
            continue
        symbol = str(row.get("symbol") or "").upper()
        intents.append(
            OrderIntent(
                intent_id=make_intent_id(cycle_id, symbol, "ENTRY_BUY_LMT", index),
                timestamp_utc=str(row.get("timestamp") or utc_now()),
                cycle_id=cycle_id,
                symbol=symbol,
                side="BUY",
                intent_type="ENTRY_BUY_LMT",
                order_type="LMT",
                source_module="paper_buy",
                strategy_source=str(row.get("inclusion_reason") or "trade_pool"),
                pool_layer=str(row.get("pool_layer") or "trade_pool"),
                market_session_state=str(row.get("market_session_state") or ""),
                bid_received=bool(row.get("bid_received")),
                ask_received=bool(row.get("ask_received")),
                quote_ready=bool(row.get("quote_ready")),
                spread_ok=bool(row.get("spread_ok")),
                position_qty_before=0.0,
                position_qty_after_expected=0.0,
                max_order_notional=float(row.get("paper_buy_max_order_notional") or paper_buy.get("paper_buy_max_order_notional") or 0),
                risk_budget_ok=bool(row.get("event_risk_ok")) and bool(row.get("gap_risk_ok")) and bool(row.get("position_sizing_ok")),
                protection_plan_required=True,
                protection_plan_exists=False,
                execution_allowed=bool(row.get("execution_allowed")),
                order_submitted=False,
                order_id=str(row.get("order_id") or ""),
                readback_status=str(row.get("readback_status") or "not_submitted"),
                blocked_reason=str(row.get("blocked_reason") or ""),
                report_path="reports/paper_buy/latest.json",
                metadata=dict(row),
            )
        )
    return intents


def protective_sell_intents(cycle_id: str) -> list[OrderIntent]:
    preview = read_json(PROJECT_ROOT / "reports" / "position_protection" / "repair_preview.json")
    rows = preview.get("proposals", []) if isinstance(preview.get("proposals"), list) else []
    if not rows:
        rows = preview.get("records", []) if isinstance(preview.get("records"), list) else []
    intents = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            continue
        symbol = str(row.get("symbol") or "").upper()
        position_qty = float(row.get("position_qty") or 0)
        recommended_qty = float(row.get("recommended_qty") or row.get("proposed_qty") or 0)
        blocked = str(row.get("blocked_reason") or row.get("reason") or "")
        execution_allowed = bool(row.get("execution_preview_allowed") or row.get("safe_to_repair")) and not blocked
        if "checks passed" in blocked.lower():
            execution_allowed = True
            blocked = "intent_only_no_order_submitted"
        intents.append(
            OrderIntent(
                intent_id=make_intent_id(cycle_id, symbol, "PROTECTIVE_SELL_STP_LMT", index),
                timestamp_utc=str(row.get("timestamp") or utc_now()),
                cycle_id=cycle_id,
                symbol=symbol,
                side="SELL",
                intent_type="PROTECTIVE_SELL_STP_LMT",
                order_type="STP LMT",
                source_module="position_protection",
                strategy_source="protective_stop_repair",
                market_session_state=str(row.get("market_session_state") or read_market_session_state()),
                bid_received=row.get("bid") is not None,
                ask_received=row.get("ask") is not None,
                quote_ready=bool(row.get("execution_preview_allowed") or row.get("safe_to_repair")),
                spread_ok=not bool(row.get("spread_too_wide")),
                position_qty_before=position_qty,
                position_qty_after_expected=max(0.0, position_qty - recommended_qty),
                max_order_notional=0.0,
                risk_budget_ok=True,
                protection_plan_required=True,
                protection_plan_exists=True,
                execution_allowed=execution_allowed,
                order_submitted=False,
                readback_status="not_submitted",
                blocked_reason=blocked or ("execution_disabled" if not execution_allowed else ""),
                report_path="reports/position_protection/repair_preview.json",
                metadata=dict(row),
            )
        )
    return intents


def gap_escape_intents(cycle_id: str) -> list[OrderIntent]:
    report = read_json(PROJECT_ROOT / "reports" / "gap_escape" / "execution_result.json")
    full = read_json(PROJECT_ROOT / "reports" / "full_paper_run" / "latest.json")
    symbols = held_symbols()
    blocked = str(report.get("blocked_reason") or full.get("blocked_reason") or "execution_disabled")
    return [
        OrderIntent(
            intent_id=make_intent_id(cycle_id, symbol, "GAP_ESCAPE_SELL_LMT", index),
            timestamp_utc=str(report.get("timestamp") or utc_now()),
            cycle_id=cycle_id,
            symbol=symbol,
            side="SELL",
            intent_type="GAP_ESCAPE_SELL_LMT",
            order_type="LMT",
            source_module="gap_escape",
            strategy_source="emergency_gap_escape",
            market_session_state=read_market_session_state(),
            bid_received=False,
            ask_received=False,
            quote_ready=False,
            spread_ok=False,
            position_qty_before=qty,
            position_qty_after_expected=qty,
            max_order_notional=0.0,
            risk_budget_ok=False,
            protection_plan_required=False,
            protection_plan_exists=False,
            execution_allowed=False,
            order_submitted=False,
            readback_status="not_submitted",
            blocked_reason=blocked,
            report_path="reports/gap_escape/execution_result.json",
            metadata=dict(report),
        )
        for index, (symbol, qty) in enumerate(symbols)
    ]


def profit_sell_intents(cycle_id: str) -> list[OrderIntent]:
    return _sell_plan_intents(
        cycle_id=cycle_id,
        intent_type="TAKE_PROFIT_SELL_LMT",
        source_module="profit_sell",
        strategy_source="take_profit_trailing_profit_lock",
        report_path="reports/execution_ledger_split/latest.json",
        blocked_reason="execution_disabled",
    )


def event_risk_sell_intents(cycle_id: str) -> list[OrderIntent]:
    return _sell_plan_intents(
        cycle_id=cycle_id,
        intent_type="EVENT_RISK_REDUCTION_SELL_LMT",
        source_module="event_risk_sell",
        strategy_source="event_risk_reduction",
        report_path="reports/execution_ledger_split/latest.json",
        blocked_reason="execution_disabled",
    )


def _sell_plan_intents(
    *,
    cycle_id: str,
    intent_type: str,
    source_module: str,
    strategy_source: str,
    report_path: str,
    blocked_reason: str,
) -> list[OrderIntent]:
    return [
        OrderIntent(
            intent_id=make_intent_id(cycle_id, symbol, intent_type, index),
            timestamp_utc=utc_now(),
            cycle_id=cycle_id,
            symbol=symbol,
            side="SELL",
            intent_type=intent_type,
            order_type="LMT",
            source_module=source_module,
            strategy_source=strategy_source,
            market_session_state=read_market_session_state(),
            position_qty_before=qty,
            position_qty_after_expected=qty,
            risk_budget_ok=True,
            execution_allowed=False,
            order_submitted=False,
            readback_status="not_submitted",
            blocked_reason=blocked_reason,
            report_path=report_path,
        )
        for index, (symbol, qty) in enumerate(held_symbols())
    ]


def options_plan_intents(cycle_id: str) -> list[OrderIntent]:
    report = read_json(PROJECT_ROOT / "reports" / "options_execution" / "latest.json")
    return [
        OrderIntent(
            intent_id=make_intent_id(cycle_id, "OPTIONS", "OPTIONS_COVERED_COLLAR_PLAN", 0),
            timestamp_utc=str(report.get("timestamp") or utc_now()),
            cycle_id=cycle_id,
            symbol="",
            side="OPTIONS",
            intent_type="OPTIONS_COVERED_COLLAR_PLAN",
            order_type="PLAN",
            source_module="options_execution",
            strategy_source="options_plan_decision_event",
            market_session_state=read_market_session_state(),
            execution_allowed=False,
            order_submitted=False,
            readback_status=str(report.get("readback_status") or "not_submitted"),
            blocked_reason=str(report.get("blocked_reason") or "plan_decision_event_only"),
            report_path="reports/options_execution/latest.json",
            metadata=dict(report),
        )
    ]


def persist_intents(intents: Sequence[OrderIntent]) -> None:
    for intent in intents:
        values = intent.sqlite_values()
        payload = json.dumps(intent.to_dict(), sort_keys=True)
        insert_event("order_intent_events", {**values, "payload_json": payload})
        if intent.intent_type in {"ENTRY_BUY_LMT", "ADD_BUY_LMT"}:
            # BUY candidates are already recorded in paper_buy_events by the full-paper runner.
            continue
        if intent.intent_type == "PROTECTIVE_SELL_STP_LMT":
            insert_event("protective_sell_events", {**values, "payload_json": payload})
        elif intent.intent_type == "GAP_ESCAPE_SELL_LMT":
            insert_event("gap_escape_events", {**values, "payload_json": payload})
        elif intent.intent_type in {"TAKE_PROFIT_SELL_LMT", "TRAILING_STOP_SELL_STP_LMT"}:
            insert_event("profit_sell_events", {**values, "payload_json": payload})
        elif intent.intent_type == "EVENT_RISK_REDUCTION_SELL_LMT":
            insert_event("event_risk_sell_events", {**values, "payload_json": payload})
        elif intent.intent_type.startswith("OPTIONS_"):
            insert_event(
                "options_order_events",
                {
                    "timestamp": intent.timestamp_utc,
                    "cycle_id": intent.cycle_id,
                    "symbol": intent.symbol,
                    "strategy": intent.strategy_source,
                    "event_type": intent.intent_type,
                    "execution_allowed": int(intent.execution_allowed),
                    "order_submitted": int(intent.order_submitted),
                    "order_id": intent.order_id,
                    "readback_status": intent.readback_status,
                    "blocked_reason": intent.blocked_reason,
                    "payload_json": payload,
                },
            )


def build_pnl_ledger_report() -> dict[str, Any]:
    ensure_paper_automation_tables()
    account = read_json(PROJECT_ROOT / "reports" / "account" / "latest.json")
    positions = read_json(PROJECT_ROOT / "reports" / "position_guard" / "latest.json")
    account_state = read_json(PROJECT_ROOT / "reports" / "account_state" / "latest.json")
    freshness = account_state.get("freshness") if isinstance(account_state.get("freshness"), Mapping) else {}
    now = utc_now()
    account_id = str(account.get("account") or account_state.get("account_id") or "")
    net_liq = to_float(account.get("net_liquidation"))
    daily_pnl = to_float(account.get("daily_pnl"))
    realized = to_float(account.get("realized_pnl"))
    unrealized = to_float(account.get("unrealized_pnl"))
    data_age = to_float(freshness.get("pnl_age_sec"))
    stale = bool(data_age is not None and data_age > 600)
    daily_return = None if not net_liq else (daily_pnl or 0.0) / net_liq
    position_rows = []
    for row in positions.get("symbols", []) if isinstance(positions.get("symbols"), list) else []:
        if not isinstance(row, Mapping):
            continue
        market_value = to_float(row.get("market_value"))
        pos_unreal = to_float(row.get("unrealized_pnl"))
        position_rows.append(
            {
                "timestamp_utc": now,
                "account_id": account_id,
                "symbol": str(row.get("symbol") or ""),
                "position_qty": to_float(row.get("position_qty")) or 0.0,
                "avg_cost": to_float(row.get("avg_cost")),
                "market_price": to_float(row.get("market_price") or row.get("last")),
                "bid": to_float(row.get("bid")),
                "ask": to_float(row.get("ask")),
                "market_value": market_value,
                "unrealized_pnl": pos_unreal,
                "realized_pnl": None,
                "daily_pnl": pos_unreal,
                "position_weight_pct": None if not net_liq or market_value is None else market_value / net_liq,
                "quote_age_sec": None if row.get("quote_age_ms") is None else (to_float(row.get("quote_age_ms")) or 0.0) / 1000.0,
                "pnl_age_sec": data_age,
                "protection_status": "covered" if row.get("position_covered_by_stop") else "uncovered_or_unknown",
                "source": "position_guard/account_reports",
                "stale": stale,
                "blocked_reason": "PnL stale" if stale else "",
            }
        )
    top_profit = max(position_rows, key=lambda item: item.get("unrealized_pnl") or float("-inf"), default={})
    top_loss = min(position_rows, key=lambda item: item.get("unrealized_pnl") or float("inf"), default={})
    trading_date = datetime.now(timezone.utc).date().isoformat()
    account_row = {
        "timestamp_utc": now,
        "account_id": account_id,
        "currency": account.get("currency") or "USD",
        "net_liquidation": net_liq,
        "daily_pnl": daily_pnl,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "daily_return_pct": None if daily_return is None else daily_return * 100.0,
        "source": "account_reports",
        "data_age_sec": data_age,
        "stale": stale,
        "blocked_reason": "PnL stale" if stale else "",
    }
    summary_row = {
        "trading_date": trading_date,
        "account_id": account_id,
        "currency": account_row["currency"],
        "net_liquidation": net_liq,
        "daily_pnl": daily_pnl,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "daily_return_pct": account_row["daily_return_pct"],
        "top_profit_symbol": top_profit.get("symbol"),
        "top_loss_symbol": top_loss.get("symbol"),
        "pnl_sample_time_utc": account.get("pnl_timestamp") or account.get("timestamp") or now,
        "data_age_sec": data_age,
        "stale": stale,
        "report_path": "reports/pnl_ledger/latest.json",
    }
    attribution_rows = attribution(position_rows, daily_pnl or 0.0, net_liq or 0.0, trading_date)
    persist_pnl(account_row, position_rows, summary_row, attribution_rows)
    return {
        "timestamp": now,
        "source": "pnl_ledger",
        "account_pnl_snapshot": account_row,
        "position_pnl_snapshots": position_rows,
        "daily_pnl_summary": summary_row,
        "symbol_pnl_attribution": attribution_rows,
        "structured_sqlite_columns": True,
        "stale_pnl_warning": stale,
    }


def persist_pnl(
    account_row: Mapping[str, Any],
    position_rows: Sequence[Mapping[str, Any]],
    summary_row: Mapping[str, Any],
    attribution_rows: Sequence[Mapping[str, Any]],
) -> None:
    with sqlite3.connect(DB_PATH) as con:
        insert_direct(con, "account_pnl_snapshots", account_row)
        insert_direct(con, "daily_pnl_summary", summary_row)
        for row in position_rows:
            insert_direct(con, "position_pnl_snapshots", row)
            insert_direct(con, "unrealized_pnl_snapshots", {
                "timestamp_utc": row.get("timestamp_utc"),
                "account_id": row.get("account_id"),
                "symbol": row.get("symbol"),
                "unrealized_pnl": row.get("unrealized_pnl"),
                "market_value": row.get("market_value"),
                "source": row.get("source"),
                "stale": int(bool(row.get("stale"))),
                "blocked_reason": row.get("blocked_reason"),
            })
        if account_row.get("realized_pnl") is not None:
            insert_direct(con, "realized_pnl_events", {
                "timestamp_utc": account_row.get("timestamp_utc"),
                "account_id": account_row.get("account_id"),
                "symbol": "",
                "realized_pnl": account_row.get("realized_pnl"),
                "source": account_row.get("source"),
                "stale": int(bool(account_row.get("stale"))),
                "blocked_reason": account_row.get("blocked_reason"),
            })
        for row in attribution_rows:
            insert_direct(con, "symbol_pnl_attribution", row)


def insert_direct(con: sqlite3.Connection, table: str, row: Mapping[str, Any]) -> None:
    columns = list(row.keys())
    placeholders = ", ".join("?" for _ in columns)
    con.execute(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})", [row.get(col) for col in columns])


def attribution(position_rows: Sequence[Mapping[str, Any]], total_daily_pnl: float, net_liq: float, trading_date: str) -> list[dict[str, Any]]:
    ranked_profit = sorted(position_rows, key=lambda item: item.get("daily_pnl") or 0.0, reverse=True)
    ranked_loss = sorted(position_rows, key=lambda item: item.get("daily_pnl") or 0.0)
    profit_rank = {row.get("symbol"): index + 1 for index, row in enumerate(ranked_profit)}
    loss_rank = {row.get("symbol"): index + 1 for index, row in enumerate(ranked_loss)}
    rows = []
    for row in position_rows:
        daily = to_float(row.get("daily_pnl")) or 0.0
        market_value = to_float(row.get("market_value")) or 0.0
        rows.append(
            {
                "trading_date": trading_date,
                "symbol": row.get("symbol"),
                "position_qty": row.get("position_qty"),
                "market_value": market_value,
                "daily_pnl": daily,
                "realized_pnl": row.get("realized_pnl"),
                "unrealized_pnl": row.get("unrealized_pnl"),
                "contribution_pct_of_total_pnl": None if total_daily_pnl == 0 else daily / total_daily_pnl * 100.0,
                "contribution_pct_of_net_liquidation": None if net_liq == 0 else daily / net_liq * 100.0,
                "rank_by_profit": profit_rank.get(row.get("symbol")),
                "rank_by_loss": loss_rank.get(row.get("symbol")),
                "stale": int(bool(row.get("stale"))),
                "notes": row.get("blocked_reason") or "",
            }
        )
    return rows


def execution_split_report(intents: Sequence[OrderIntent], pnl_report: Mapping[str, Any]) -> dict[str, Any]:
    counts = count_intents(intents)
    ready_for_next_active_session = counts["submitted_orders"] == 0 and not bool(pnl_report.get("stale_pnl_warning"))
    return {
        "timestamp": utc_now(),
        "source": "execution_ledger_split",
        "buy_separated_from_sell": True,
        "counts": counts,
        "order_submitted_count": sum(1 for item in intents if item.order_submitted),
        "live_trading_used": False,
        "market_order_used": any(item.order_type == "MKT" for item in intents),
        "paid_snapshot_used": False,
        "regulatory_snapshot_used": False,
        "intents": [item.to_dict() for item in intents],
        "blocked_reasons": count_values(item.blocked_reason for item in intents if item.blocked_reason),
        "ready_for_next_active_session_5_minute_paper_test": ready_for_next_active_session,
        "ready_blocked_reasons": {
            "stale_pnl_warning": bool(pnl_report.get("stale_pnl_warning")),
        },
    }


def separation_report_payload(intents: Sequence[OrderIntent], pnl_report: Mapping[str, Any]) -> dict[str, Any]:
    counts = count_intents(intents)
    ready_for_next_active_session = counts["submitted_orders"] == 0 and not bool(pnl_report.get("stale_pnl_warning"))
    return {
        "timestamp": utc_now(),
        "source": "buy_sell_separation",
        "answers": {
            "is_buy_separated_from_sell": True,
            "buy_intent_events": counts["buy"],
            "protective_sell_intent_events": counts["protective_sell"],
            "gap_escape_sell_intent_events": counts["gap_escape_sell"],
            "profit_sell_intent_events": counts["profit_sell"],
            "event_risk_sell_intent_events": counts["event_risk_sell"],
            "options_plan_events": counts["options_plan"],
            "did_any_event_submit_order": counts["submitted_orders"] > 0,
            "did_any_event_use_live_trading": False,
            "did_any_event_use_market_order": any(item.order_type == "MKT" for item in intents),
            "did_any_event_use_paid_or_regulatory_snapshot": False,
            "is_pnl_stored_in_structured_sqlite_columns": bool(pnl_report.get("structured_sqlite_columns")),
            "current_blocker_reasons": count_values(item.blocked_reason for item in intents if item.blocked_reason),
            "ready_for_next_active_session_5_minute_paper_test": ready_for_next_active_session,
            "ready_blocked_reasons": {
                "stale_pnl_warning": bool(pnl_report.get("stale_pnl_warning")),
            },
        },
    }


def count_intents(intents: Sequence[OrderIntent]) -> dict[str, int]:
    return {
        "buy": sum(1 for item in intents if item.side == "BUY"),
        "protective_sell": sum(1 for item in intents if item.intent_type == "PROTECTIVE_SELL_STP_LMT"),
        "gap_escape_sell": sum(1 for item in intents if item.intent_type == "GAP_ESCAPE_SELL_LMT"),
        "profit_sell": sum(1 for item in intents if item.intent_type in {"TAKE_PROFIT_SELL_LMT", "TRAILING_STOP_SELL_STP_LMT"}),
        "event_risk_sell": sum(1 for item in intents if item.intent_type == "EVENT_RISK_REDUCTION_SELL_LMT"),
        "options_plan": sum(1 for item in intents if item.side == "OPTIONS"),
        "submitted_orders": sum(1 for item in intents if item.order_submitted),
    }


def write_reports(execution_report: Mapping[str, Any], pnl_report: Mapping[str, Any], separation_report: Mapping[str, Any]) -> None:
    for directory, report in [
        (EXECUTION_SPLIT_DIR, execution_report),
        (PNL_LEDGER_DIR, pnl_report),
        (SEPARATION_DIR, separation_report),
    ]:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "latest.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        (directory / "latest.md").write_text(markdown(report), encoding="utf-8")


def markdown(report: Mapping[str, Any]) -> str:
    lines = [f"# {report.get('source')}", "", f"- timestamp: {report.get('timestamp')}"]
    if "counts" in report:
        for key, value in report["counts"].items():
            lines.append(f"- {key}: {value}")
    if "answers" in report and isinstance(report["answers"], Mapping):
        for key, value in report["answers"].items():
            lines.append(f"- {key}: {value}")
    if report.get("source") == "pnl_ledger":
        account = report.get("account_pnl_snapshot") if isinstance(report.get("account_pnl_snapshot"), Mapping) else {}
        lines.extend([
            f"- account_id: {account.get('account_id')}",
            f"- net_liquidation: {account.get('net_liquidation')}",
            f"- daily_pnl: {account.get('daily_pnl')}",
            f"- stale_pnl_warning: {report.get('stale_pnl_warning')}",
        ])
    return "\n".join(lines) + "\n"


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def held_symbols() -> list[tuple[str, float]]:
    guard = read_json(PROJECT_ROOT / "reports" / "position_guard" / "latest.json")
    rows = []
    for row in guard.get("symbols", []) if isinstance(guard.get("symbols"), list) else []:
        if isinstance(row, Mapping) and float(row.get("position_qty") or 0) > 0:
            rows.append((str(row.get("symbol") or "").upper(), float(row.get("position_qty") or 0)))
    return rows


def read_market_session_state() -> str:
    market = read_json(PROJECT_ROOT / "reports" / "market_session" / "latest.json")
    return str(market.get("session_state") or "UNKNOWN")


def count_values(values: Iterable[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return result


def to_float(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None
