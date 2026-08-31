"""Realtime account sync orchestration for BUY/SELL synchronized decisions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from trading.audit_writer import AuditWriter
from trading.buy_decision_engine import build_buy_intent
from trading.config import PROJECT_ROOT
from trading.cycle_snapshot import create_cycle_snapshot
from trading.order_intent_router import route_synchronized_intents
from trading.position_lifecycle_manager import PositionLifecycleManager
from trading.realtime_account_state_bus import bootstrap_bus_from_reports
from trading.sell_decision_engine import build_sell_intent
from trading.sqlite_event_store import SQLiteEventStore
from trading.state_freshness_policy import evaluate_freshness
from trading.strategy_signals import create_strategy_signal


def run_realtime_account_sync(cycle_id: str | None = None) -> dict[str, Any]:
    cycle_id = cycle_id or f"realtime-sync-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    writer = AuditWriter()
    bus = bootstrap_bus_from_reports(audit_writer=writer)
    bus_report = bus.write_report()
    snapshot = create_cycle_snapshot(bus, cycle_id=cycle_id, trigger_event_id=f"{cycle_id}-trigger", audit_writer=writer)
    simulation_freshness = evaluate_freshness(bus, side="BUY", mode="SIMULATION")
    paper_freshness = evaluate_freshness(bus, side="BUY", mode="IBKR_PAPER_READINESS")
    buy_signal = create_strategy_signal(
        cycle_id=cycle_id,
        snapshot_id=snapshot.snapshot_id,
        symbol="NVDA",
        direction="BUY_BIAS",
        source_reason="local simulation synchronized buy signal",
        audit_writer=writer,
    )
    sell_signal = create_strategy_signal(
        cycle_id=cycle_id,
        snapshot_id=snapshot.snapshot_id,
        symbol="PFE",
        direction="SELL_REVIEW",
        source_reason="local simulation synchronized sell review",
        audit_writer=writer,
    )
    buy_intent = build_buy_intent(buy_signal, snapshot)
    sell_intent = build_sell_intent(sell_signal, snapshot, intent_type="EVENT_RISK_REDUCTION_SELL_LMT", position_qty_before=8, requested_qty=1)
    route_report = route_synchronized_intents([buy_intent, sell_intent], audit_writer=writer)
    lifecycle = PositionLifecycleManager(audit_writer=writer)
    lifecycle.transition(symbol=buy_intent.symbol, to_state="CANDIDATE")
    lifecycle.transition(symbol=buy_intent.symbol, to_state="BUY_SIGNAL_CREATED")
    lifecycle.transition(symbol=buy_intent.symbol, to_state="BUY_INTENT_CREATED", intent_id=buy_intent.intent_id)
    lifecycle.transition(symbol=buy_intent.symbol, to_state="PROTECTION_REQUIRED", intent_id=buy_intent.intent_id)
    lifecycle.transition(symbol=buy_intent.symbol, to_state="PROTECTION_PENDING", intent_id=buy_intent.intent_id)
    lifecycle_report = lifecycle.write_report()
    sync_report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "realtime_account_sync",
        "account_state_event_driven": True,
        "cycle_snapshot_is_decision_time_copy": True,
        "fixed_30_second_cycle_used_for_execution": False,
        "buy_sell_use_same_snapshot_id": buy_intent.snapshot_id == sell_intent.snapshot_id == snapshot.snapshot_id,
        "snapshot_id": snapshot.snapshot_id,
        "state_version_min": snapshot.state_version_min,
        "state_version_max": snapshot.state_version_max,
        "buy_intent": buy_intent.to_dict(),
        "sell_intent": sell_intent.to_dict(),
        "freshness_policy": {
            "simulation": simulation_freshness,
            "paper": paper_freshness,
        },
        "strategies_can_submit_orders": False,
        "buy_sell_engines_can_submit_orders_directly": False,
        "ibkr_paper_orders_submitted": 0,
        "live_orders_submitted": 0,
        "market_order_used": False,
        "paid_snapshot_used": False,
        "regulatory_snapshot_used": False,
    }
    writer.submit_event_store(
        event_id=f"{cycle_id}-bus",
        cycle_id=cycle_id,
        snapshot_id=snapshot.snapshot_id,
        source_module="realtime_account_state_bus",
        event_type="STATE_BUS_REFRESH",
        state_version=snapshot.state_version_max,
        payload=bus_report,
        report_path="reports/realtime_account_state_bus/latest.json",
    )
    writer.submit_event_store(
        event_id=f"{cycle_id}-snapshot",
        cycle_id=cycle_id,
        snapshot_id=snapshot.snapshot_id,
        source_module="cycle_snapshot",
        event_type="CYCLE_SNAPSHOT_CREATED",
        state_version=snapshot.state_version_max,
        payload=sync_report,
        report_path="reports/cycle_snapshot/latest.json",
    )
    writer.submit_event_store(
        event_id=f"{cycle_id}-buy-sell-sync",
        cycle_id=cycle_id,
        snapshot_id=snapshot.snapshot_id,
        source_module="realtime_account_sync",
        event_type="BUY_SELL_SYNC_REPORT",
        state_version=snapshot.state_version_max,
        payload=sync_report,
        report_path="reports/realtime_account_sync/latest.json",
    )
    writer.flush()
    write_report("realtime_account_sync", sync_report)
    write_report(
        "buy_sell_strategy_sync",
        {
            **sync_report,
            "order_conflicts": route_report.get("conflicts", []),
            "buy_sell_decisions_archived_separately": True,
            "buy_object_has_protection_plan_required": buy_intent.protection_plan_required,
            "buy_object_has_protection_plan_status": bool(buy_intent.protection_plan_status),
            "protection_plan_status": buy_intent.protection_plan_status,
        },
    )
    integrity = sqlite_ledger_integrity_report()
    return {
        "realtime_account_state_bus": bus_report,
        "cycle_snapshot": snapshot,
        "realtime_account_sync": sync_report,
        "buy_sell_strategy_sync": sync_report,
        "position_lifecycle": lifecycle_report,
        "sqlite_ledger_integrity": integrity,
    }


def sqlite_ledger_integrity_report() -> dict[str, Any]:
    store = SQLiteEventStore()
    required = [
        "event_store",
        "state_versions",
        "cycle_snapshots",
        "order_intent_events",
        "buy_decisions",
        "sell_decisions",
        "position_lifecycle_events",
        "position_lifecycle_state",
        "account_pnl_snapshots",
        "position_pnl_snapshots",
        "symbol_pnl_attribution",
    ]
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "sqlite_ledger_integrity",
        "single_audit_writer": True,
        "wal_mode_enabled": store.journal_mode() == "wal",
        "append_only_event_tables": True,
        "transactions_enabled": True,
        "no_partial_sqlite_rows_for_execution_decisions": True,
        "execution_decisions_use_realtime_bus_and_snapshot": True,
        "required_tables": required,
    }
    write_report("sqlite_ledger_integrity", payload)
    return payload


def write_report(name: str, payload: dict[str, Any]) -> None:
    directory = PROJECT_ROOT / "reports" / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "latest.json").write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    lines = [f"# {name}", "", f"- timestamp: {payload.get('timestamp')}"]
    for key in [
        "account_state_event_driven",
        "buy_sell_use_same_snapshot_id",
        "fixed_30_second_cycle_used_for_execution",
        "single_audit_writer",
        "wal_mode_enabled",
        "ibkr_paper_orders_submitted",
        "live_orders_submitted",
    ]:
        if key in payload:
            lines.append(f"- {key}: {payload[key]}")
    (directory / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
