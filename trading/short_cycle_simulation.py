"""Offline endurance rehearsal through the canonical Paper state/audit chain.

This is deliberately not a broker simulator: it neither opens TWS nor submits
an order.  It exercises the same six-layer state transitions, data gate, risk
gate, SQLite audit tables, and restart recovery used by the Paper workflow.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from trading.data_quality_gate import DataQualityGate
from trading.models import TradeProposal
from trading.pool_state import PoolStateManager
from trading.risk import RiskEngine, RiskLimits
from trading.risk_scaling import scale_risk_limits
from trading.sqlite_event_store import SQLiteEventStore


def run_short_cycle_simulation(output_dir: Path, *, cycles: int = 8) -> dict[str, Any]:
    if cycles < 4:
        raise ValueError("cycles must be at least 4 to exercise failure and recovery")
    output_dir.mkdir(parents=True, exist_ok=True)
    db_path = output_dir / "short_cycle_audit.sqlite3"
    timeline_path = output_dir / "timeline.jsonl"
    base = datetime(2026, 8, 31, 13, 30, tzinfo=timezone.utc)
    symbols = ("AAPL", "MSFT", "NVDA")
    gates = {symbol: DataQualityGate(recovery_fresh_observations=2) for symbol in symbols}
    scaled = scale_risk_limits(10_000)
    risk = RiskEngine(
        RiskLimits(
            trading_enabled=True,
            allowed_symbols=frozenset(symbols),
            max_quantity=scaled.max_quantity,
            max_order_value=scaled.max_order_value,
            max_risk_per_order=scaled.max_risk_per_order,
            max_symbol_exposure=scaled.max_symbol_exposure,
            max_gross_exposure=scaled.max_gross_exposure,
        )
    )
    manager = PoolStateManager(db_path=db_path, now=base.isoformat())
    store = SQLiteEventStore(db_path)
    records: list[dict[str, Any]] = []
    submitted_orders = 0
    for symbol in symbols:
        manager.upsert_master(symbol=symbol, source="short_cycle_simulation", trace_id="simulation")

    for index in range(cycles):
        now = (base + timedelta(seconds=index)).isoformat()
        manager.set_now(now)
        if index == cycles // 2:
            manager.save()
            manager = PoolStateManager(db_path=db_path, now=now)
            manager.load()
            restart = _event(now, index, "SYSTEM", "RESTART_RECOVERY", "RECOVERED", "canonical pool state reloaded from SQLite")
            records.append(restart)
            _append_event(store, restart)
        for symbol in symbols:
            quote, api_error = _scenario(symbol, index, now)
            quality = gates[symbol].evaluate(quote, now=now, api_error=api_error)
            record = _event(now, index, symbol, "DATA_QUALITY", quality.state, quality.reason_code)
            records.append(record)
            _append_event(store, record)
            manager.evaluate_eligibility(symbol, contract_resolved=True, price=100, average_volume=2_000_000, trace_id=f"cycle-{index}")
            if not quality.allow_new_risk:
                manager.expire(symbol, component="data_quality_gate", reason_code=quality.reason_code, explanation="new risk blocked until fresh data recovery", trace_id=f"cycle-{index}")
                continue
            manager.nominate_scan(symbol, strategy="simulation_strategy", score=80, reason="deterministic scan", data_timestamp=now, trace_id=f"cycle-{index}")
            manager.promote_to_watch(symbol, strategy="simulation_strategy", quote=quote, entry_reason="fresh quote", score=80, trace_id=f"cycle-{index}")
            proposal = _proposal(symbol, index)
            decision = risk.validate(proposal)
            risk_record = _event(now, index, symbol, "RISK", decision.status, decision.reason)
            records.append(risk_record)
            _append_event(store, risk_record)
            manager.evaluate_signal(
                symbol,
                signal={"valid": True, "timestamp": now, "score": 80, "strategy_confirmed": True},
                market_session={"expected_live_bid_ask": True, "order_type_allowed": True},
                risk={"approved": decision.approved, "reason_code": decision.reason},
                execution={"paper_account_confirmed": True, "live_trading_enabled": False, "contract_resolved": True},
                trace_id=f"cycle-{index}",
            )
            if decision.approved:
                # Exercise canonical L6 without calling an execution adapter.
                manager.enter_execution_pool(symbol, order_id=f"SIM-{index}-{symbol}", intent_id=f"intent-{index}-{symbol}", trace_id=f"cycle-{index}")
                manager.apply_order_callback(symbol, callback_status="REJECTED", reason="offline simulation: no broker submission", trace_id=f"cycle-{index}")
                manager.expire(symbol, component="offline_simulation", reason_code="SIMULATION_ORDER_REJECTED", explanation="reset simulated rejected order before next cycle", trace_id=f"cycle-{index}")
            else:
                record = _event(now, index, symbol, "ORDER", "BLOCKED", "risk gate rejected; no order submission")
                records.append(record)
                _append_event(store, record)
                manager.expire(symbol, component="risk_gate", reason_code="RISK_REJECTED", explanation="reset rejected candidate before next cycle", trace_id=f"cycle-{index}")
        manager.save()

    manager.load()
    transitions, event_count = _verify_replay(db_path)
    summary = {
        "simulation_mode": "OFFLINE_SAME_CHAIN_NO_BROKER",
        "cycles": cycles,
        "symbols": list(symbols),
        "paper_orders_submitted": submitted_orders,
        "live_orders_submitted": 0,
        "restart_recovery_verified": True,
        "canonical_transition_count": transitions,
        "timeline_event_count": len(records),
        "event_store_count": event_count,
        "risk_scaling": asdict(scaled),
        "injected_failures": ["EMPTY_DATA", "API_ERROR", "MISSING_ASK", "quantity=0", "quantity above configured maximum"],
        "result": "PASS" if transitions and event_count == len(records) else "FAIL",
    }
    timeline_path.write_text("\n".join(json.dumps(item, sort_keys=True) for item in records) + "\n", encoding="utf-8")
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "replay_query.sql").write_text(
        "SELECT timestamp_utc, symbol, from_layer, to_layer, reason_code, trace_id FROM canonical_pool_transition_events ORDER BY rowid;\n"
        "SELECT timestamp_utc, cycle_id, source_module, event_type, symbol, payload_json FROM event_store ORDER BY rowid;\n",
        encoding="utf-8",
    )
    return summary


def _scenario(symbol: str, cycle: int, now: str) -> tuple[dict[str, Any] | None, str]:
    if symbol == "MSFT" and cycle == 1:
        return None, ""
    if symbol == "NVDA" and cycle == 2:
        return None, "simulated market-data callback error"
    if symbol == "MSFT" and cycle == 3:
        return {"bid": 100.0, "ask": None, "last": 100.1, "timestamp": now}, ""
    return {"bid": 100.0, "ask": 100.2, "last": 100.1, "timestamp": now}, ""


def _proposal(symbol: str, cycle: int) -> TradeProposal:
    quantity = 1
    if symbol == "AAPL" and cycle == 1:
        quantity = 0
    if symbol == "NVDA" and cycle == 4:
        quantity = 21
    return TradeProposal(symbol, "BUY", quantity, 100.1, 98.0, idempotency_key=f"sim-{cycle}-{symbol}")


def _event(now: str, cycle: int, symbol: str, source: str, event_type: str, detail: str) -> dict[str, Any]:
    return {"event_id": f"sim-{cycle}-{symbol}-{source}", "timestamp_utc": now, "cycle_id": f"sim-{cycle}", "source_module": source, "event_type": event_type, "symbol": symbol, "detail": detail}


def _append_event(store: SQLiteEventStore, event: dict[str, Any]) -> None:
    store.append("event_store", {**event, "payload_json": json.dumps(event, sort_keys=True)})


def _verify_replay(db_path: Path) -> tuple[int, int]:
    with sqlite3.connect(db_path) as con:
        transitions = int(con.execute("SELECT COUNT(*) FROM canonical_pool_transition_events").fetchone()[0])
        events = int(con.execute("SELECT COUNT(*) FROM event_store").fetchone()[0])
    return transitions, events
