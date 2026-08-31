"""Order intent router. Emits synchronized intent events only."""

from __future__ import annotations

import json
from typing import Sequence

from trading.audit_writer import AuditWriter
from trading.config import PROJECT_ROOT
from trading.order_intents import OrderIntent
from trading.sell_decision_engine import priority


REPORT_DIR = PROJECT_ROOT / "reports" / "order_conflicts"


def route_synchronized_intents(intents: Sequence[OrderIntent], *, audit_writer: AuditWriter | None = None) -> dict:
    writer = audit_writer or AuditWriter()
    by_symbol: dict[str, list[OrderIntent]] = {}
    for intent in intents:
        by_symbol.setdefault(intent.symbol, []).append(intent)
    routed: list[OrderIntent] = []
    conflicts = []
    for symbol, symbol_intents in by_symbol.items():
        sells = [intent for intent in symbol_intents if intent.side == "SELL"]
        buys = [intent for intent in symbol_intents if intent.side == "BUY"]
        high_priority_sell = sorted(sells, key=priority)[0] if sells else None
        for buy in buys:
            if high_priority_sell and priority(high_priority_sell) <= 2:
                conflicts.append(
                    {
                        "event_id": f"conflict-{buy.intent_id}-{high_priority_sell.intent_id}",
                        "timestamp_utc": buy.timestamp_utc,
                        "cycle_id": buy.cycle_id,
                        "snapshot_id": buy.snapshot_id,
                        "symbol": symbol,
                        "conflict_type": "BUY_BLOCKED_BY_HIGH_PRIORITY_SELL",
                        "buy_intent_id": buy.intent_id,
                        "sell_intent_id": high_priority_sell.intent_id,
                        "decision": "block_buy",
                        "blocked_reason": "same_symbol_high_priority_sell",
                    }
                )
            else:
                routed.append(buy)
        routed.extend(sells)
    for intent in routed:
        payload = json.dumps(intent.to_dict(), sort_keys=True)
        writer.submit("order_intent_events", {**intent.sqlite_values(), "payload_json": payload})
        writer.submit(
            "router_decisions",
            {
                "event_id": intent.event_id or intent.intent_id,
                "timestamp_utc": intent.timestamp_utc,
                "cycle_id": intent.cycle_id,
                "snapshot_id": intent.snapshot_id,
                "symbol": intent.symbol,
                "decision": "routed_intent_only",
                "execution_allowed": int(intent.execution_allowed),
                "blocked_reason": intent.blocked_reason,
                "payload_json": payload,
            },
        )
    for conflict in conflicts:
        writer.submit("order_conflict_events", {**conflict, "payload_json": json.dumps(conflict, sort_keys=True)})
    writer.flush()
    report = {
        "timestamp": routed[0].timestamp_utc if routed else "",
        "source": "order_intent_router",
        "routed_intents": [intent.to_dict() for intent in routed],
        "conflicts": conflicts,
        "buy_sell_use_same_snapshot_id": len({intent.snapshot_id for intent in intents}) <= 1,
        "orders_submitted": 0,
        "ibkr_paper_orders_submitted": 0,
        "live_orders_submitted": 0,
    }
    write_conflict_report(report)
    return report


def write_conflict_report(report: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "latest.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    (REPORT_DIR / "latest.md").write_text(
        f"# Order Conflicts\n\n- conflict_count: {len(report['conflicts'])}\n- orders_submitted: 0\n",
        encoding="utf-8",
    )


def run(discovery_run_id: str = "manual-order-intents") -> dict:
    from trading.auto_open_pipeline import (
        PipelineConfig,
        run_discovery_orchestrator,
        run_dynamic_pool,
        run_fast_order_guidance,
        run_ibkr_scanner,
        run_news_pipeline,
        run_order_intent_router,
    )

    config = PipelineConfig.from_env()
    discovery = run_discovery_orchestrator(discovery_run_id, config)
    scanner = run_ibkr_scanner(discovery_run_id, config)
    news = run_news_pipeline(discovery_run_id, config, discovery, scanner)
    pool = run_dynamic_pool(discovery_run_id, config, discovery, scanner, news)
    guidance = run_fast_order_guidance(discovery_run_id, config, scanner, news, pool)
    return run_order_intent_router(discovery_run_id, config, guidance, pool)
