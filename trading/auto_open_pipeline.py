"""Auto-open local discovery, news, dynamic pool, and simulation pipeline.

This module is deliberately local/simulated. It can create candidates, guidance,
order intents, and SIMULATED_ORDER rows, but it never submits IBKR paper orders
or live orders.
"""

from __future__ import annotations

import csv
import json
import os
import socket
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from trading.config import PROJECT_ROOT, Settings
from trading.order_intents import OrderIntent, make_intent_id
from trading.paper_audit_db import ensure_paper_automation_tables, insert_event
from trading.realtime_account_sync import run_realtime_account_sync


DEFAULT_UNIVERSE = PROJECT_ROOT / "data" / "us_equity_universe.csv"
SCAN_CODES = [
    "TOP_PERC_GAIN",
    "TOP_PERC_LOSE",
    "HOT_BY_VOLUME",
    "MOST_ACTIVE",
    "HIGH_OPEN_GAP",
    "LOW_OPEN_GAP",
    "HIGH_REL_VOLUME",
    "TOP_TRADE_RATE",
    "TOP_VOLUME_RATE",
    "HIGH_OPT_VOLUME_PUT_CALL_RATIO",
]
POOL_NAMES = [
    "security_master",
    "discovery_universe",
    "tradable_universe",
    "stream_eligible_pool",
    "monitor_pool",
    "hot_pool",
    "trade_pool",
]


@dataclass(frozen=True)
class PipelineConfig:
    discovery_enabled: bool = True
    scanner_enabled: bool = True
    news_trigger_enabled: bool = True
    external_sources_enabled: bool = True
    pool_expansion_enabled: bool = True
    intent_generation_enabled: bool = True
    local_simulation_enabled: bool = True
    fast_order_guidance_enabled: bool = True
    ibkr_paper_order_submission: bool = False
    live_trading_enabled: bool = False
    allow_market_orders: bool = False
    allow_paid_snapshot: bool = False
    allow_regulatory_snapshot: bool = False
    mock_scanner_enabled: bool = True
    news_fixture_enabled: bool = True
    trade_pool_size: int = 12
    simulated_fill_enabled: bool = True

    @classmethod
    def from_env(cls) -> "PipelineConfig":
        return cls(
            discovery_enabled=read_bool("DISCOVERY_ENABLED", True),
            scanner_enabled=read_bool("SCANNER_ENABLED", True),
            news_trigger_enabled=read_bool("NEWS_TRIGGER_ENABLED", True),
            external_sources_enabled=read_bool("EXTERNAL_SOURCES_ENABLED", True),
            pool_expansion_enabled=read_bool("POOL_EXPANSION_ENABLED", True),
            intent_generation_enabled=read_bool("INTENT_GENERATION_ENABLED", True),
            local_simulation_enabled=read_bool("LOCAL_SIMULATION_ENABLED", True),
            fast_order_guidance_enabled=read_bool("FAST_ORDER_GUIDANCE_ENABLED", True),
            ibkr_paper_order_submission=read_bool("IBKR_PAPER_ORDER_SUBMISSION", False),
            live_trading_enabled=read_bool("LIVE_TRADING_ENABLED", False),
            allow_market_orders=read_bool("ALLOW_MARKET_ORDERS", False),
            allow_paid_snapshot=read_bool("ALLOW_PAID_SNAPSHOT", False),
            allow_regulatory_snapshot=read_bool("ALLOW_REGULATORY_SNAPSHOT", False),
            mock_scanner_enabled=read_bool("MOCK_SCANNER_ENABLED", True),
            news_fixture_enabled=read_bool("NEWS_FIXTURE_ENABLED", True),
            trade_pool_size=max(5, min(50, int(os.getenv("DYNAMIC_TRADE_POOL_SIZE", "12")))),
            simulated_fill_enabled=read_bool("SIMULATED_FILL_ENABLED", True),
        )


def run_auto_open_pipeline(stage: str = "full", *, config: PipelineConfig | None = None) -> dict[str, Any]:
    ensure_paper_automation_tables()
    config = config or PipelineConfig.from_env()
    assert_simulation_safety(config)
    run_id = f"auto-open-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    discovery = run_discovery_orchestrator(run_id, config)
    scanner = run_ibkr_scanner(run_id, config)
    news = run_news_pipeline(run_id, config, discovery, scanner)
    pool = run_dynamic_pool(run_id, config, discovery, scanner, news)
    guidance = run_fast_order_guidance(run_id, config, scanner, news, pool)
    intents = run_order_intent_router(run_id, config, guidance, pool)
    simulation = run_local_simulation(run_id, config, intents, pool)
    paper_gate = run_paper_execution_gate(run_id, config, simulation)
    realtime_sync = run_realtime_account_sync(cycle_id=run_id)
    audit = write_final_audit(run_id, config, discovery, scanner, news, pool, guidance, intents, simulation, paper_gate)
    return {
        "run_id": run_id,
        "stage": stage,
        "discovery": discovery,
        "scanner": scanner,
        "news": news,
        "pool": pool,
        "guidance": guidance,
        "order_intent_router": intents,
        "simulation": simulation,
        "paper_execution_gate": paper_gate,
        "realtime_account_sync": realtime_sync,
        "final_audit": audit,
    }


def assert_simulation_safety(config: PipelineConfig) -> None:
    if config.live_trading_enabled:
        raise RuntimeError("LIVE_TRADING_ENABLED must remain false")
    if config.ibkr_paper_order_submission:
        raise RuntimeError("IBKR_PAPER_ORDER_SUBMISSION must remain false")
    if config.allow_market_orders:
        raise RuntimeError("ALLOW_MARKET_ORDERS must remain false")
    if config.allow_paid_snapshot:
        raise RuntimeError("ALLOW_PAID_SNAPSHOT must remain false")
    if config.allow_regulatory_snapshot:
        raise RuntimeError("ALLOW_REGULATORY_SNAPSHOT must remain false")


def run_discovery_orchestrator(run_id: str, config: PipelineConfig) -> dict[str, Any]:
    now = utc_now()
    universe = load_universe_rows()
    seed_symbols = [row["symbol"] for row in universe[:25]]
    position_symbols = current_position_symbols()
    open_order_symbols = open_order_symbols_from_reports()
    source_specs = [
        ("STATIC_SEED", "STATIC", True, True, seed_symbols, "seed universe"),
        ("MANUAL_WATCHLIST", "MANUAL", True, True, env_symbols("MANUAL_WATCHLIST", "AAPL,MSFT,NVDA"), "manual watchlist"),
        ("TWS_IBKR_SCANNER", "IBKR_SCANNER", config.scanner_enabled, tws_available(), [], "scanner source is handled by ibkr_scanner"),
        ("CACHED_SCANNER", "CACHED_SCANNER", config.scanner_enabled, (PROJECT_ROOT / "reports" / "scanner_candidates" / "latest.json").exists(), cached_scanner_symbols(), "cached scanner"),
        ("MOCK_SCANNER", "MOCK_SCANNER", config.scanner_enabled, config.mock_scanner_enabled, ["AMD", "MU", "PLTR", "SMCI"], "configured mock scanner"),
        ("EXTERNAL_MARKET_DATA_SOURCES", "EXTERNAL", config.external_sources_enabled, True, ["QQQ", "SPY", "IWM"], "local external fixture"),
        ("IBKR_NEWS", "IBKR_NEWS", config.news_trigger_enabled, True, [], "news source is handled by news pipeline"),
        ("FREE_NEWS_RSS", "FREE_RSS", config.news_trigger_enabled, config.news_fixture_enabled, ["NVDA", "AAPL", "TSLA"], "fixture RSS headlines"),
        ("SEC_FILINGS", "SEC", config.news_trigger_enabled, config.news_fixture_enabled, ["META", "MSFT"], "fixture SEC filings"),
        ("EARNINGS_CALENDAR", "EARNINGS", config.news_trigger_enabled, config.news_fixture_enabled, ["PFE", "T"], "fixture earnings calendar"),
        ("CURRENT_POSITIONS", "ACCOUNT", True, True, position_symbols, "current positions"),
        ("OPEN_ORDERS", "ACCOUNT", True, True, open_order_symbols, "open orders"),
        ("RESEARCH_WORKER_CANDIDATES", "RESEARCH", True, True, research_symbols(), "research worker candidates"),
    ]
    candidates: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []
    for source_name, source_type, enabled, configured, symbols, reason in source_specs:
        available = bool(configured)
        used = bool(enabled and configured and symbols)
        status = source_status(enabled, configured, available, used)
        if source_name == "TWS_IBKR_SCANNER" and enabled and not available:
            status = "UNAVAILABLE"
        entry = {
            "timestamp": now,
            "discovery_run_id": run_id,
            "source_name": source_name,
            "source_type": source_type,
            "enabled": enabled,
            "configured": configured,
            "available": available,
            "used": used,
            "status": status,
            "candidate_count": len(symbols) if used else 0,
            "error_message": "" if available else "source unavailable or not configured",
            "report_path": "reports/discovery_orchestrator/latest.json",
        }
        statuses.append(entry)
        insert_event("discovery_source_status", {**bool_to_ints(entry), "payload_json": json.dumps(entry, sort_keys=True)})
        for index, symbol in enumerate(symbols):
            row = {
                "timestamp": now,
                "discovery_run_id": run_id,
                "symbol": symbol,
                "source_name": source_name,
                "source_type": source_type,
                "inclusion_reason": reason,
                "blocked_reason": "",
                "score": 50.0 + max(0, 10 - index),
            }
            candidates.append(row)
            insert_event("discovery_candidates", {**row, "payload_json": json.dumps(row, sort_keys=True)})
    report = {
        "timestamp": now,
        "discovery_run_id": run_id,
        "source": "discovery_orchestrator",
        "local_simulation_enabled": config.local_simulation_enabled,
        "ibkr_paper_order_submission": config.ibkr_paper_order_submission,
        "live_trading_enabled": config.live_trading_enabled,
        "source_status": statuses,
        "candidates": candidates,
        "candidate_count": len(candidates),
        "orders_submitted": 0,
    }
    insert_event(
        "discovery_runs",
        {
            "timestamp": now,
            "discovery_run_id": run_id,
            "status": "OK",
            "sources_used": sum(1 for item in statuses if item["used"]),
            "candidates_count": len(candidates),
            "local_simulation_enabled": int(config.local_simulation_enabled),
            "ibkr_paper_order_submission": int(config.ibkr_paper_order_submission),
            "live_trading_enabled": int(config.live_trading_enabled),
            "payload_json": json.dumps(report, sort_keys=True),
        },
    )
    write_report("discovery_orchestrator", report)
    return report


def run_ibkr_scanner(run_id: str, config: PipelineConfig) -> dict[str, Any]:
    now = utc_now()
    tws_ok = tws_available()
    results: list[dict[str, Any]] = []
    status = "TWS_UNAVAILABLE"
    source_type = "MOCK_SCANNER" if config.mock_scanner_enabled else "CACHED_SCANNER"
    if config.scanner_enabled and tws_ok:
        status = "TWS_AVAILABLE_LOCAL_SIMULATION_SCANNER_USED"
        source_type = "IBKR_SCANNER"
    elif config.scanner_enabled and config.mock_scanner_enabled:
        status = "USED_FIXTURE"
    elif config.scanner_enabled and cached_scanner_symbols():
        status = "USED_CACHE"
    for scan_index, code in enumerate(SCAN_CODES):
        symbols = scanner_symbols_for_code(code)
        for rank, symbol in enumerate(symbols, start=1):
            row = {
                "timestamp_utc": now,
                "discovery_run_id": run_id,
                "source_type": source_type,
                "scan_code": code,
                "rank": rank,
                "symbol": symbol,
                "conId": "",
                "exchange": "SMART",
                "primaryExchange": "NASDAQ" if symbol not in {"PFE", "T", "SPY", "IWM"} else "NYSE",
                "currency": "USD",
                "secType": "STK",
                "distance": "",
                "benchmark": "",
                "projection": "",
                "raw_payload_ref": f"scanner_fixture:{code}:{rank}",
                "included_in_discovery": True,
                "blocked_reason": "" if code != "HIGH_OPT_VOLUME_PUT_CALL_RATIO" else "metadata_only",
                "score": max(20.0, 90.0 - scan_index * 3 - rank),
            }
            results.append(row)
            insert_event("ibkr_scanner_results", {**bool_to_ints(row), "payload_json": json.dumps(row, sort_keys=True)})
            insert_event(
                "scanner_candidates",
                {
                    "timestamp": now,
                    "discovery_run_id": run_id,
                    "symbol": symbol,
                    "source_type": source_type,
                    "scan_code": code,
                    "rank": rank,
                    "score": row["score"],
                    "included_in_discovery": int(row["included_in_discovery"]),
                    "blocked_reason": row["blocked_reason"],
                    "payload_json": json.dumps(row, sort_keys=True),
                },
            )
    report = {
        "timestamp": now,
        "discovery_run_id": run_id,
        "source": "ibkr_scanner",
        "status": status,
        "tws_available": tws_ok,
        "tws_scanner_pipeline_ran": config.scanner_enabled,
        "live_tws_scanner_request_used": False,
        "scanner_result_origin": "local_simulation_fixture",
        "scanner_codes": SCAN_CODES,
        "scanner_candidates": results,
        "candidate_count": len(results),
        "cancel_scanner_subscriptions": True,
        "scanner_can_submit_orders": False,
        "paid_snapshot_used": False,
        "regulatory_snapshot_used": False,
        "orders_submitted": 0,
    }
    insert_event(
        "ibkr_scanner_runs",
        {
            "timestamp": now,
            "discovery_run_id": run_id,
            "status": status,
            "tws_available": int(tws_ok),
            "scanner_codes_tested": len(SCAN_CODES),
            "candidates_count": len(results),
            "paid_snapshot_used": 0,
            "regulatory_snapshot_used": 0,
            "payload_json": json.dumps(report, sort_keys=True),
        },
    )
    write_report("ibkr_scanner", report)
    write_report("scanner_candidates", {"timestamp": now, "discovery_run_id": run_id, "source": "scanner_candidates", "records": results, "candidate_count": len(results)})
    return report


def run_news_pipeline(run_id: str, config: PipelineConfig, discovery: Mapping[str, Any], scanner: Mapping[str, Any]) -> dict[str, Any]:
    now = utc_now()
    providers = news_provider_status(run_id, config)
    interface_tests = ibkr_news_interface_tests(run_id, providers)
    raw = raw_news_fixture(run_id, config, discovery, scanner)
    structured = [structure_news_event(item) for item in raw]
    candidate_events: list[dict[str, Any]] = []
    risk_events: list[dict[str, Any]] = []
    for event in structured:
        candidate = {
            "timestamp": now,
            "discovery_run_id": run_id,
            "event_id": event["event_id"],
            "symbol": event["symbol"],
            "action": event["action"],
            "score_delta": 20.0 if event["action"] in {"ADD_TO_HOT_POOL", "FAST_BUY_GUIDANCE"} else -30.0 if event["action"] == "BLOCK_BUY" else 5.0,
            "routed_to_pool": event["action"] in {"ADD_TO_DISCOVERY", "ADD_TO_HOT_POOL", "FAST_BUY_GUIDANCE", "BOOST_SCORE"},
            "blocked_reason": "" if event["action"] != "BLOCK_BUY" else event["reason"],
        }
        candidate_events.append(candidate)
        insert_event("news_candidate_events", {**bool_to_ints(candidate), "payload_json": json.dumps(candidate, sort_keys=True)})
        risk = {
            "timestamp": now,
            "discovery_run_id": run_id,
            "event_id": event["event_id"],
            "symbol": event["symbol"],
            "risk_level": event["risk_level"],
            "action": event["action"],
            "buy_blocked": event["action"] == "BLOCK_BUY",
            "sell_review_required": event["action"] == "SELL_REVIEW",
            "reason": event["reason"],
        }
        risk_events.append(risk)
        insert_event("event_risk_events", {**bool_to_ints(risk), "payload_json": json.dumps(risk, sort_keys=True)})
    report = {
        "timestamp": now,
        "discovery_run_id": run_id,
        "source": "news_pipeline",
        "providers": providers,
        "interface_tests": interface_tests,
        "raw_news_events": raw,
        "structured_news_events": structured,
        "news_candidate_events": candidate_events,
        "event_risk_events": risk_events,
        "news_can_submit_orders": False,
        "orders_submitted": 0,
    }
    write_report("ibkr_news", {"timestamp": now, "discovery_run_id": run_id, "providers": providers, "IBKR_NEWS_AVAILABLE": any(p["available"] for p in providers if p["provider_type"] == "IBKR_NEWS")})
    write_report("ibkr_news_interface_tests", {"timestamp": now, "discovery_run_id": run_id, "interface_tests": interface_tests})
    write_report("news_event_monitor", {"timestamp": now, "discovery_run_id": run_id, "raw_news_events": raw, "orders_submitted": 0})
    write_report("structured_news_events", {"timestamp": now, "discovery_run_id": run_id, "structured_news_events": structured})
    write_report("news_candidate_router", {"timestamp": now, "discovery_run_id": run_id, "news_candidate_events": candidate_events, "news_can_submit_orders": False})
    write_report("event_risk", {"timestamp": now, "discovery_run_id": run_id, "event_risk_events": risk_events})
    return report


def news_provider_status(run_id: str, config: PipelineConfig) -> list[dict[str, Any]]:
    now = utc_now()
    tws_ok = tws_available()
    providers = [
        ("IBKR_NEWS", "IBKR_NEWS", "IBKR", True, tws_ok, "IBKR_NEWS_AVAILABLE" if tws_ok else "IBKR_NEWS_NOT_SUBSCRIBED"),
        ("FREE_RSS", "FREE_RSS", "RSS", config.news_fixture_enabled, True, "USED_FIXTURE"),
        ("SEC_FILINGS", "SEC_FILINGS", "SEC", config.news_fixture_enabled, True, "USED_FIXTURE"),
        ("EARNINGS_CALENDAR", "EARNINGS_CALENDAR", "EARN", config.news_fixture_enabled, True, "USED_FIXTURE"),
        ("LOCAL_NEWS_CACHE", "LOCAL_CACHE", "CACHE", True, True, "AVAILABLE"),
        ("NEWS_FIXTURE", "FIXTURE", "FIX", config.news_fixture_enabled, True, "USED_FIXTURE"),
    ]
    rows = []
    for name, ptype, code, configured, available, status in providers:
        row = {
            "timestamp": now,
            "discovery_run_id": run_id,
            "provider_name": name,
            "provider_type": ptype,
            "provider_code": code,
            "enabled": config.news_trigger_enabled,
            "configured": configured,
            "available": available and configured,
            "is_live": ptype == "IBKR_NEWS" and tws_ok,
            "requires_subscription": ptype == "IBKR_NEWS",
            "status": status,
            "last_success_at": now if available and configured and ptype != "IBKR_NEWS" else "",
            "last_error": "" if available and configured else "not subscribed or unavailable",
        }
        rows.append(row)
        insert_event(
            "ibkr_news_provider_status",
            {
                "timestamp": now,
                "discovery_run_id": run_id,
                "provider_code": code,
                "provider_name": name,
                "enabled": int(row["enabled"]),
                "available": int(row["available"]),
                "status": status,
                "error_message": row["last_error"],
                "payload_json": json.dumps(row, sort_keys=True),
            },
        )
    return rows


def ibkr_news_interface_tests(run_id: str, providers: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    now = utc_now()
    ibkr_available = any(p.get("provider_type") == "IBKR_NEWS" and p.get("available") for p in providers)
    interfaces = [
        "reqNewsProviders",
        "contract_generic_news_tick",
        "broadtape_news_contract",
        "reqHistoricalNews",
        "reqNewsArticle",
        "news_bulletins_optional",
    ]
    rows = []
    for interface in interfaces:
        status = "PROVIDER_AVAILABLE" if ibkr_available and interface == "reqNewsProviders" else "IBKR_NEWS_NOT_SUBSCRIBED"
        row = {
            "timestamp": now,
            "discovery_run_id": run_id,
            "interface_name": interface,
            "status": status,
            "provider_code": "IBKR",
            "symbol": "",
            "conId": "",
            "headline_count": 0,
            "error_message": "" if status == "PROVIDER_AVAILABLE" else "TWS/news entitlement unavailable; pipeline continues with RSS/SEC/earnings fixtures",
        }
        rows.append(row)
        insert_event("ibkr_news_interface_tests", {**row, "payload_json": json.dumps(row, sort_keys=True)})
    return rows


def raw_news_fixture(run_id: str, config: PipelineConfig, discovery: Mapping[str, Any], scanner: Mapping[str, Any]) -> list[dict[str, Any]]:
    now = utc_now()
    if not config.news_trigger_enabled:
        return []
    fixture = [
        ("FREE_RSS", "NVDA", "NVIDIA relative volume surges before the open", "rss:nvda:relvol"),
        ("SEC_FILINGS", "META", "Meta files 8-K update with no urgent risk flag", "sec:meta:8k"),
        ("EARNINGS_CALENDAR", "PFE", "Pfizer earnings date approaches; review event risk", "earn:pfe:calendar"),
        ("NEWS_FIXTURE", "TSLA", "Tesla litigation headline triggers buy block review", "fixture:tsla:litigation"),
    ]
    rows = []
    for index, (source, symbol, headline, ref) in enumerate(fixture):
        row = {
            "timestamp_utc": now,
            "discovery_run_id": run_id,
            "event_id": f"{run_id}-news-{index}",
            "source": source,
            "provider_code": source,
            "symbol": symbol,
            "headline": headline,
            "source_url_or_ref": ref,
            "raw_payload_ref": ref,
        }
        rows.append(row)
        insert_event("raw_news_events", {**row, "payload_json": json.dumps(row, sort_keys=True)})
    return rows


def structure_news_event(row: Mapping[str, Any]) -> dict[str, Any]:
    headline = str(row.get("headline", ""))
    lower = headline.lower()
    event_type = "COMPANY_NEWS"
    action = "ADD_TO_DISCOVERY"
    risk_level = "LOW"
    urgency = "MEDIUM"
    sentiment = "neutral"
    reason = "normalized fixture/news event"
    if "earnings" in lower:
        event_type = "EARNINGS"
        action = "SELL_REVIEW"
        risk_level = "MEDIUM"
        urgency = "HIGH"
        reason = "earnings calendar event requires risk review"
    elif "litigation" in lower:
        event_type = "LITIGATION"
        action = "BLOCK_BUY"
        risk_level = "HIGH"
        urgency = "HIGH"
        sentiment = "negative"
        reason = "litigation headline blocks fast buy"
    elif "relative volume" in lower or "surges" in lower:
        action = "FAST_BUY_GUIDANCE"
        urgency = "HIGH"
        sentiment = "positive"
        reason = "urgent volume/news combination"
    event = {
        **dict(row),
        "conId": "",
        "company_name": "",
        "event_type": event_type,
        "summary": headline,
        "sentiment": sentiment,
        "urgency": urgency,
        "confidence": 0.75,
        "expected_impact": "candidate_score_adjustment",
        "risk_level": risk_level,
        "action": action,
        "reason": reason,
        "dedup_key": f"{row.get('source')}:{row.get('symbol')}:{headline[:40]}",
    }
    insert_event("structured_news_events", {**event, "payload_json": json.dumps(event, sort_keys=True)})
    return event


def run_dynamic_pool(run_id: str, config: PipelineConfig, discovery: Mapping[str, Any], scanner: Mapping[str, Any], news: Mapping[str, Any]) -> dict[str, Any]:
    now = utc_now()
    candidates = consolidate_candidates(discovery, scanner, news)
    scores = []
    memberships = []
    for symbol, details in candidates.items():
        score = score_candidate(symbol, details)
        scores.append(score)
        for component, value in score["components"].items():
            insert_event(
                "candidate_score_components",
                {
                    "timestamp": now,
                    "discovery_run_id": run_id,
                    "symbol": symbol,
                    "component_name": component,
                    "component_value": value,
                    "reason": f"{component} from local discovery/simulation pipeline",
                    "payload_json": json.dumps(score, sort_keys=True),
                },
            )
        insert_event("candidate_scores", {**score["flat"], "timestamp": now, "discovery_run_id": run_id, "payload_json": json.dumps(score, sort_keys=True)})
    ranked = sorted(scores, key=lambda item: (-item["flat"]["final_candidate_score"], item["symbol"]))
    trade_symbols = {item["symbol"] for item in ranked[: config.trade_pool_size]}
    hot_symbols = {item["symbol"] for item in ranked if item["flat"]["news_score"] > 0 or item["flat"]["final_candidate_score"] >= 75}
    monitor_symbols = set(current_position_symbols()) | set(open_order_symbols_from_reports())
    pools: dict[str, list[str]] = {name: [] for name in POOL_NAMES}
    for item in ranked:
        symbol = item["symbol"]
        add_pool_membership(memberships, run_id, symbol, "security_master", True, details_reason(candidates[symbol]), item["flat"]["final_candidate_score"])
        add_pool_membership(memberships, run_id, symbol, "discovery_universe", True, "source candidate", item["flat"]["final_candidate_score"])
        add_pool_membership(memberships, run_id, symbol, "tradable_universe", True, "passed local tradable filters", item["flat"]["final_candidate_score"])
        add_pool_membership(memberships, run_id, symbol, "stream_eligible_pool", True, "eligible for simulated stream/readiness", item["flat"]["final_candidate_score"])
        if symbol in monitor_symbols:
            add_pool_membership(memberships, run_id, symbol, "monitor_pool", True, "current position/open order forced monitor", item["flat"]["final_candidate_score"])
        if symbol in hot_symbols:
            add_pool_membership(memberships, run_id, symbol, "hot_pool", True, "high score or urgent news", item["flat"]["final_candidate_score"])
        if symbol in trade_symbols:
            add_pool_membership(memberships, run_id, symbol, "trade_pool", True, "top scored local simulation candidate", item["flat"]["final_candidate_score"])
        insert_event(
            "security_master",
            {
                "timestamp": now,
                "discovery_run_id": run_id,
                "symbol": symbol,
                "company_name": candidates[symbol].get("company_name", ""),
                "source_types": ",".join(sorted(candidates[symbol]["source_types"])),
                "source_details": json.dumps(candidates[symbol]["source_details"], sort_keys=True),
                "current_layer": "trade_pool" if symbol in trade_symbols else "hot_pool" if symbol in hot_symbols else "discovery_universe",
                "first_seen_at": now,
                "last_seen_at": now,
                "included": 1,
                "blocked_reason": "",
                "payload_json": json.dumps(candidates[symbol], sort_keys=True),
            },
        )
        for src in candidates[symbol]["source_details"]:
            insert_event(
                "pool_source_events",
                {
                    "timestamp": now,
                    "discovery_run_id": run_id,
                    "symbol": symbol,
                    "source_type": src.get("source_type"),
                    "source_name": src.get("source_name"),
                    "reason": src.get("reason"),
                    "score": src.get("score"),
                    "payload_json": json.dumps(src, sort_keys=True),
                },
            )
    for row in memberships:
        pools[row["pool_name"]].append(row["symbol"])
        insert_event("pool_membership_history", {**bool_to_ints(row), "payload_json": json.dumps(row, sort_keys=True)})
        insert_event(
            "pool_transition_events",
            {
                "timestamp": now,
                "cycle_id": run_id,
                "symbol": row["symbol"],
                "from_pool": "",
                "to_pool": row["pool_name"],
                "decision": "include" if row["included"] else "exclude",
                "blocked_reason": row["blocked_reason"],
                "payload_json": json.dumps(row, sort_keys=True),
            },
        )
    decisions = []
    for item in ranked:
        symbol = item["symbol"]
        decision = {
            "timestamp": now,
            "cycle_id": run_id,
            "symbol": symbol,
            "pool_layer": "trade_pool" if symbol in trade_symbols else "discovery_universe",
            "inclusion_reason": "top scored local simulation candidate" if symbol in trade_symbols else "not top trade_pool candidate",
            "blocked_reason": "" if symbol in trade_symbols else "below_trade_pool_cutoff",
            "market_session_state": market_session_state(),
            "expected_live_bid_ask": False,
            "bid_received": False,
            "ask_received": False,
            "quote_ready": False,
            "spread_ok": True,
            "event_risk_ok": symbol != "TSLA",
            "gap_risk_ok": True,
            "position_sizing_ok": True,
            "decision": "include" if symbol in trade_symbols else "exclude",
            "execution_allowed": False,
            "order_submitted": False,
            "order_id": "",
            "readback_status": "not_submitted",
        }
        decisions.append(decision)
        insert_event("trade_pool_decisions", {**bool_to_ints(decision), "payload_json": json.dumps(decision, sort_keys=True)})
    pool_report = {
        "timestamp": now,
        "discovery_run_id": run_id,
        "source": "dynamic_pool",
        "pool_counts": {name: len(set(values)) for name, values in pools.items()},
        "pools": {name: sorted(set(values)) for name, values in pools.items()},
        "membership": memberships,
        "trade_pool_decisions": decisions,
        "candidate_scores": ranked,
        "top_candidates": ranked[:50],
        "scanner_news_external_cannot_bypass_layers": True,
        "current_positions_always_monitor_pool": True,
        "orders_submitted": 0,
    }
    write_report("pool_audit", pool_report)
    write_report("pool_membership", {"timestamp": now, "discovery_run_id": run_id, "records": memberships, "pool_counts": pool_report["pool_counts"]}, append_history=True)
    write_report("pool_transition", {"timestamp": now, "discovery_run_id": run_id, "transitions": memberships})
    write_report("trade_pool_decisions", {"timestamp": now, "discovery_run_id": run_id, "records": decisions})
    write_report("candidate_scoring", {"timestamp": now, "discovery_run_id": run_id, "records": ranked})
    write_report("top_candidates", {"timestamp": now, "discovery_run_id": run_id, "records": ranked[:50]})
    return pool_report


def run_fast_order_guidance(run_id: str, config: PipelineConfig, scanner: Mapping[str, Any], news: Mapping[str, Any], pool: Mapping[str, Any]) -> dict[str, Any]:
    now = utc_now()
    trade_symbols = set(pool.get("pools", {}).get("trade_pool", []))
    structured = list(news.get("structured_news_events", []))
    rows = []
    for index, event in enumerate(structured):
        symbol = str(event.get("symbol", "")).upper()
        direction = "MONITOR_ONLY"
        intent_type = "NONE"
        blocked = ""
        if event.get("action") == "FAST_BUY_GUIDANCE":
            direction = "BUY_BIAS"
            intent_type = "ENTRY_BUY_LMT"
            blocked = "" if symbol in trade_symbols else "not_in_trade_pool"
        elif event.get("action") == "BLOCK_BUY":
            direction = "BLOCK_BUY"
            blocked = event.get("reason", "event risk blocks buy")
        elif event.get("action") == "SELL_REVIEW":
            direction = "SELL_REVIEW"
            intent_type = "EVENT_RISK_REDUCTION_SELL_LMT"
            blocked = "sell_review_only"
        row = {
            "timestamp_utc": now,
            "discovery_run_id": run_id,
            "guidance_id": f"{run_id}-guidance-{index}",
            "symbol": symbol,
            "source_event_id": event.get("event_id", ""),
            "source_type": event.get("source", "NEWS"),
            "urgency": event.get("urgency", "MEDIUM"),
            "confidence": event.get("confidence", 0.5),
            "direction": direction,
            "recommended_intent_type": intent_type,
            "reason": event.get("reason", ""),
            "required_gates": ["trade_pool", "market_session", "quote_freshness", "spread", "risk_budget", "position_check", "pnl_fresh"],
            "allowed_to_submit_order": False,
            "routed_to_order_intent_router": intent_type != "NONE",
            "blocked_reason": blocked,
        }
        rows.append(row)
    for index, candidate in enumerate(scanner.get("scanner_candidates", [])[:8], start=len(rows)):
        symbol = str(candidate.get("symbol", "")).upper()
        intent_type = "ENTRY_BUY_LMT" if symbol in trade_symbols else "NONE"
        row = {
            "timestamp_utc": now,
            "discovery_run_id": run_id,
            "guidance_id": f"{run_id}-guidance-{index}",
            "symbol": symbol,
            "source_event_id": f"scanner:{candidate.get('scan_code')}:{candidate.get('rank')}",
            "source_type": "SCANNER",
            "urgency": "HIGH" if candidate.get("scan_code") in {"TOP_PERC_GAIN", "HOT_BY_VOLUME", "HIGH_REL_VOLUME"} else "MEDIUM",
            "confidence": 0.65,
            "direction": "BUY_BIAS" if symbol in trade_symbols else "MONITOR_ONLY",
            "recommended_intent_type": intent_type,
            "reason": f"scanner {candidate.get('scan_code')} candidate; guidance only",
            "required_gates": ["trade_pool", "market_session", "quote_freshness", "spread", "risk_budget", "position_check", "pnl_fresh"],
            "allowed_to_submit_order": False,
            "routed_to_order_intent_router": intent_type != "NONE",
            "blocked_reason": "" if intent_type != "NONE" else "not_in_trade_pool",
        }
        rows.append(row)
    for row in rows:
        insert_event("fast_order_guidance_events", {**bool_to_ints(row), "required_gates": ",".join(row["required_gates"]), "payload_json": json.dumps(row, sort_keys=True)})
    report = {
        "timestamp": now,
        "discovery_run_id": run_id,
        "source": "fast_order_guidance",
        "records": rows,
        "fast_guidance_can_submit_orders": False,
        "generated_order_intent_candidates": sum(1 for row in rows if row["routed_to_order_intent_router"]),
        "orders_submitted": 0,
    }
    write_report("fast_order_guidance", report)
    return report


def run_order_intent_router(run_id: str, config: PipelineConfig, guidance: Mapping[str, Any], pool: Mapping[str, Any]) -> dict[str, Any]:
    now = utc_now()
    intents: list[OrderIntent] = []
    refs = {
        "account_state_ref": "reports/account_state/latest.json",
        "position_state_ref": "reports/position_guard/latest.json",
        "quote_state_ref": "reports/quote_state/latest.json",
        "pnl_state_ref": "reports/pnl_ledger/latest.json",
        "market_session_ref": "reports/market_session/latest.json",
        "pool_state_ref": "reports/pool_membership/latest.json",
        "trigger_state_ref": "reports/fast_order_guidance/latest.json",
        "news_state_ref": "reports/structured_news_events/latest.json",
        "scanner_state_ref": "reports/scanner_candidates/latest.json",
    }
    for index, row in enumerate(guidance.get("records", [])):
        intent_type = row.get("recommended_intent_type")
        if intent_type not in {"ENTRY_BUY_LMT", "EVENT_RISK_REDUCTION_SELL_LMT"}:
            continue
        side = "BUY" if intent_type == "ENTRY_BUY_LMT" else "SELL"
        order_type = "LMT"
        blocked = row.get("blocked_reason") or "local_simulation_only_no_ibkr_order"
        intent = OrderIntent(
            intent_id=make_intent_id(run_id, str(row.get("symbol", "")), str(intent_type), index),
            timestamp_utc=now,
            cycle_id=run_id,
            symbol=str(row.get("symbol", "")).upper(),
            side=side,
            intent_type=str(intent_type),
            order_type=order_type,
            source_module="order_intent_router",
            snapshot_id=run_id,
            state_version=0,
            state_version_min=0,
            state_version_max=0,
            source_trigger_id=str(row.get("source_event_id", "")),
            strategy_source=str(row.get("source_type", "fast_order_guidance")),
            pool_layer="trade_pool" if row.get("symbol") in set(pool.get("pools", {}).get("trade_pool", [])) else "",
            market_session_state=market_session_state(),
            bid_received=False,
            ask_received=False,
            quote_ready=False,
            spread_ok=True,
            position_qty_before=0.0,
            position_qty_after_expected=1.0 if side == "BUY" else 0.0,
            max_order_notional=25.0,
            risk_budget_ok=True,
            protection_plan_required=side == "BUY",
            protection_plan_exists=False,
            protection_plan_mode="DEFERRED",
            protection_plan_status="PENDING" if side == "BUY" else "",
            execution_allowed=False,
            simulated_order_submitted=False,
            ibkr_paper_order_submitted=False,
            live_order_submitted=False,
            order_submitted=False,
            readback_status="not_submitted",
            blocked_reason=blocked,
            report_path="reports/order_intent_router/latest.json",
            metadata={**dict(row), **refs},
        )
        intents.append(intent)
        payload = json.dumps(intent.to_dict(), sort_keys=True)
        insert_event("order_intent_events", {**intent.sqlite_values(), "payload_json": payload})
        if side == "BUY":
            insert_event(
                "buy_decisions",
                {
                    "timestamp": now,
                    "cycle_id": run_id,
                    "symbol": intent.symbol,
                    "intent_id": intent.intent_id,
                    "decision": "intent_only_local_simulation",
                    "execution_allowed": 0,
                    "order_submitted": 0,
                    "blocked_reason": blocked,
                    "payload_json": payload,
                },
            )
        else:
            insert_event(
                "sell_decisions",
                {
                    "timestamp": now,
                    "cycle_id": run_id,
                    "symbol": intent.symbol,
                    "intent_id": intent.intent_id,
                    "intent_type": intent.intent_type,
                    "decision": "intent_only_local_simulation",
                    "execution_allowed": 0,
                    "order_submitted": 0,
                    "blocked_reason": blocked,
                    "payload_json": payload,
                },
            )
    report = {
        "timestamp": now,
        "discovery_run_id": run_id,
        "source": "order_intent_router",
        "snapshot_refs": refs,
        "buy_sell_use_same_cycle_snapshot_refs": True,
        "intents": [intent.to_dict() for intent in intents],
        "intent_count": len(intents),
        "order_submitted_count": 0,
        "live_trading_used": False,
        "market_order_used": False,
        "paid_snapshot_used": False,
        "regulatory_snapshot_used": False,
    }
    write_report("order_intent_router", report)
    write_report(
        "buy_sell_modularization",
        {
            "timestamp": now,
            "discovery_run_id": run_id,
            "buy_modules": ["discovery", "pool_manager", "fast_order_guidance", "order_intent_router", "buy_decisions"],
            "sell_modules": ["event_risk_control", "fast_order_guidance", "order_intent_router", "sell_decisions"],
            "scanner_can_submit_orders": False,
            "news_can_submit_orders": False,
            "pool_manager_can_submit_orders": False,
            "fast_guidance_can_submit_orders": False,
            "final_executor_enabled": False,
            "buy_sell_use_same_cycle_snapshot_refs": True,
        },
    )
    write_report(
        "module_isolation_audit",
        {
            "timestamp": now,
            "discovery_run_id": run_id,
            "modules": {
                "scanner": {"can_submit_orders": False},
                "news": {"can_submit_orders": False},
                "external_sources": {"can_submit_orders": False},
                "pool_manager": {"can_submit_orders": False},
                "strategy": {"can_submit_orders_directly": False},
                "fast_order_guidance": {"can_submit_orders": False},
                "paper_executor": {"enabled": False},
            },
            "orders_submitted": 0,
        },
    )
    return report


def run_local_simulation(run_id: str, config: PipelineConfig, intent_report: Mapping[str, Any], pool: Mapping[str, Any]) -> dict[str, Any]:
    now = utc_now()
    if not config.local_simulation_enabled:
        report = {"timestamp": now, "simulation_run_id": run_id, "status": "disabled", "simulated_orders": [], "orders_submitted": 0}
        write_report("simulation_run", report)
        return report
    simulated_orders = []
    executions = []
    positions: dict[str, dict[str, float]] = {}
    for index, intent in enumerate(intent_report.get("intents", [])):
        if intent.get("side") != "BUY":
            continue
        symbol = intent["symbol"]
        price = simulated_price(symbol)
        order = {
            "timestamp_utc": now,
            "simulation_run_id": run_id,
            "simulated_order_id": f"{run_id}-sim-order-{index}",
            "intent_id": intent["intent_id"],
            "symbol": symbol,
            "side": "BUY",
            "intent_type": intent["intent_type"],
            "order_type": "LMT",
            "quantity": 1.0,
            "limit_price": price,
            "status": "SIMULATED_ORDER",
            "order_submitted": False,
            "ibkr_paper_order_submitted": False,
            "live_order_submitted": False,
        }
        simulated_orders.append(order)
        insert_event("simulated_order_ledger", {**bool_to_ints(order), "payload_json": json.dumps(order, sort_keys=True)})
        if config.simulated_fill_enabled:
            execution = {
                "timestamp_utc": now,
                "simulation_run_id": run_id,
                "simulated_execution_id": f"{run_id}-sim-fill-{index}",
                "simulated_order_id": order["simulated_order_id"],
                "symbol": symbol,
                "side": "BUY",
                "quantity": 1.0,
                "fill_price": price,
                "fill_status": "SIMULATED_FILL",
            }
            executions.append(execution)
            insert_event("simulated_execution_ledger", {**execution, "payload_json": json.dumps(execution, sort_keys=True)})
            positions[symbol] = {"position_qty": positions.get(symbol, {}).get("position_qty", 0.0) + 1.0, "avg_cost": price}
    position_rows = []
    simulated_cash = 100_000.0
    simulated_equity = simulated_cash
    for symbol, state in positions.items():
        market = simulated_price(symbol) * 1.002
        qty = state["position_qty"]
        value = qty * market
        pnl = qty * (market - state["avg_cost"])
        simulated_cash -= qty * state["avg_cost"]
        simulated_equity += pnl
        row = {
            "timestamp_utc": now,
            "simulation_run_id": run_id,
            "symbol": symbol,
            "position_qty": qty,
            "avg_cost": state["avg_cost"],
            "market_price": market,
            "market_value": value,
            "unrealized_pnl": pnl,
        }
        position_rows.append(row)
        insert_event("simulated_position_snapshots", {**row, "payload_json": json.dumps(row, sort_keys=True)})
    pnl = {
        "timestamp_utc": now,
        "simulation_run_id": run_id,
        "account_id": "LOCAL_SIMULATION",
        "currency": "USD",
        "simulated_cash": simulated_cash,
        "simulated_equity": simulated_equity,
        "simulated_daily_pnl": simulated_equity - 100_000.0,
    }
    insert_event("simulated_pnl_snapshots", {**pnl, "payload_json": json.dumps(pnl, sort_keys=True)})
    report = {
        "timestamp": now,
        "simulation_run_id": run_id,
        "source": "local_simulation",
        "mode": "LOCAL_SIMULATION_ONLY",
        "simulated_orders": simulated_orders,
        "simulated_executions": executions,
        "simulated_positions": position_rows,
        "simulated_pnl": pnl,
        "simulated_orders_count": len(simulated_orders),
        "simulated_fills_count": len(executions),
        "ibkr_paper_orders_submitted": 0,
        "live_orders_submitted": 0,
        "orders_submitted": 0,
    }
    write_report("simulation_run", report)
    write_report("simulation_orders", {"timestamp": now, "simulation_run_id": run_id, "mode": "LOCAL_SIMULATION_ONLY", "records": simulated_orders, "ibkr_paper_orders_submitted": 0})
    write_report("simulation_pnl", {"timestamp": now, "simulation_run_id": run_id, "mode": "LOCAL_SIMULATION_ONLY", "simulated_pnl": pnl, "positions": position_rows})
    return report


def run_paper_execution_gate(run_id: str, config: PipelineConfig, simulation: Mapping[str, Any]) -> dict[str, Any]:
    now = utc_now()
    checks = {
        "explicit_config_true": config.ibkr_paper_order_submission,
        "confirmed_paper_account": False,
        "tws_connected": tws_available(),
        "market_session_active": market_session_state() in {"PREMARKET", "REGULAR", "AFTERHOURS"},
        "fresh_bid_ask": False,
        "pnl_fresh": False,
        "account_position_state_fresh": False,
        "process_guard_ok": True,
        "execution_lock_ok": True,
        "no_duplicate_process": True,
        "no_paid_snapshot": not config.allow_paid_snapshot,
        "no_regulatorySnapshot": not config.allow_regulatory_snapshot,
        "no_market_order": not config.allow_market_orders,
        "local_simulation_passed": simulation.get("mode") == "LOCAL_SIMULATION_ONLY",
        "paper_micro_test_approved": False,
        "max_order_notional_small": True,
        "order_readback_required": True,
    }
    blocked = [name for name, ok in checks.items() if not ok]
    report = {
        "timestamp": now,
        "cycle_id": run_id,
        "source": "paper_execution_gate",
        "paper_execution_interface_exists": True,
        "paper_execution_enabled": False,
        "IBKR_PAPER_ORDER_SUBMISSION": config.ibkr_paper_order_submission,
        "AUTO_ENABLE_IBKR_PAPER_ORDER_SUBMISSION": False,
        "LIVE_TRADING_ENABLED": config.live_trading_enabled,
        "future_activation_conditions": checks,
        "gate_status": "blocked_default_false",
        "blocked_reason": ",".join(blocked),
        "orders_submitted": 0,
    }
    insert_event(
        "paper_execution_gate_events",
        {
            "timestamp": now,
            "cycle_id": run_id,
            "paper_execution_enabled": 0,
            "live_trading_enabled": int(config.live_trading_enabled),
            "ibkr_paper_order_submission": int(config.ibkr_paper_order_submission),
            "gate_status": report["gate_status"],
            "blocked_reason": report["blocked_reason"],
            "payload_json": json.dumps(report, sort_keys=True),
        },
    )
    for name, ok in checks.items():
        insert_event(
            "paper_order_readiness_events",
            {
                "timestamp": now,
                "cycle_id": run_id,
                "readiness_key": name,
                "ready": int(ok),
                "blocked_reason": "" if ok else name,
                "payload_json": json.dumps({"key": name, "ready": ok}, sort_keys=True),
            },
        )
    write_report("paper_execution_gate", report)
    write_report("paper_order_readiness", {"timestamp": now, "cycle_id": run_id, "records": checks, "paper_execution_enabled": False})
    return report


def write_final_audit(
    run_id: str,
    config: PipelineConfig,
    discovery: Mapping[str, Any],
    scanner: Mapping[str, Any],
    news: Mapping[str, Any],
    pool: Mapping[str, Any],
    guidance: Mapping[str, Any],
    intents: Mapping[str, Any],
    simulation: Mapping[str, Any],
    paper_gate: Mapping[str, Any],
) -> dict[str, Any]:
    now = utc_now()
    pools = pool.get("pools", {})
    providers = news.get("providers", [])
    interface_tests = news.get("interface_tests", [])
    audit = {
        "timestamp": now,
        "discovery_run_id": run_id,
        "source": "final_auto_open_discovery_news_simulation_audit",
        "discovery_enabled": config.discovery_enabled,
        "scanner_enabled": config.scanner_enabled,
        "news_enabled": config.news_trigger_enabled,
        "pool_expansion_enabled": config.pool_expansion_enabled,
        "intent_generation_enabled": config.intent_generation_enabled,
        "local_simulation_enabled": config.local_simulation_enabled,
        "sources_used": [row["source_name"] for row in discovery.get("source_status", []) if row.get("used")],
        "sources_unavailable": [row for row in discovery.get("source_status", []) if row.get("status") in {"UNAVAILABLE", "NOT_CONFIGURED", "ERROR"}],
        "tws_scanner_ran": bool(scanner.get("tws_scanner_pipeline_ran")),
        "live_tws_scanner_request_used": bool(scanner.get("live_tws_scanner_request_used")),
        "scanner_status": scanner.get("status"),
        "scanner_candidates_count": scanner.get("candidate_count", 0),
        "ibkr_news_interfaces_tested": len(interface_tests),
        "ibkr_news_providers_available": [p for p in providers if p.get("provider_type") == "IBKR_NEWS" and p.get("available")],
        "ibkr_news_interfaces_work": [t for t in interface_tests if t.get("status") == "PROVIDER_AVAILABLE"],
        "ibkr_news_interfaces_failed": [t for t in interface_tests if t.get("status") != "PROVIDER_AVAILABLE"],
        "all_news_sources_under_registry": True,
        "news_generated_fast_order_guidance": bool(guidance.get("records")),
        "fast_guidance_generated_order_intents": intents.get("intent_count", 0) > 0,
        "news_scanner_source_direct_submit_order": False,
        "security_master_size": len(pools.get("security_master", [])),
        "discovery_universe_size": len(pools.get("discovery_universe", [])),
        "tradable_universe_size": len(pools.get("tradable_universe", [])),
        "stream_eligible_pool_size": len(pools.get("stream_eligible_pool", [])),
        "monitor_pool_size": len(pools.get("monitor_pool", [])),
        "hot_pool_size": len(pools.get("hot_pool", [])),
        "trade_pool_size": len(pools.get("trade_pool", [])),
        "top_50_candidates": pool.get("top_candidates", []),
        "source_attribution_by_symbol": source_attribution(pool.get("membership", [])),
        "score_breakdown_by_symbol": {row["symbol"]: row["components"] for row in pool.get("candidate_scores", [])},
        "simulated_orders_count": simulation.get("simulated_orders_count", 0),
        "simulated_pnl_generated": bool(simulation.get("simulated_pnl")),
        "ibkr_paper_orders_submitted": 0,
        "live_orders_submitted": 0,
        "paid_snapshot_used": False,
        "regulatory_snapshot_used": False,
        "market_order_used": False,
        "buy_sell_use_same_cycle_snapshot_refs": intents.get("buy_sell_use_same_cycle_snapshot_refs", True),
        "paper_execution_interface_exists": paper_gate.get("paper_execution_interface_exists"),
        "paper_execution_default_false": paper_gate.get("paper_execution_enabled") is False,
        "tests_passed": read_bool("PIPELINE_TESTS_PASSED", False),
        "tests_command": os.getenv("PIPELINE_TESTS_COMMAND", "external pytest not run inside pipeline"),
    }
    write_report("final_auto_open_discovery_news_simulation_audit", audit)
    return audit


def consolidate_candidates(discovery: Mapping[str, Any], scanner: Mapping[str, Any], news: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}

    def add(symbol: str, source_type: str, source_name: str, reason: str, score: float = 50.0) -> None:
        symbol = symbol.strip().upper()
        if not symbol:
            return
        state = result.setdefault(symbol, {"symbol": symbol, "source_types": set(), "source_details": [], "company_name": ""})
        state["source_types"].add(source_type)
        state["source_details"].append({"source_type": source_type, "source_name": source_name, "reason": reason, "score": score})

    for row in discovery.get("candidates", []):
        add(str(row.get("symbol", "")), str(row.get("source_type", "")), str(row.get("source_name", "")), str(row.get("inclusion_reason", "")), float(row.get("score") or 50))
    for row in scanner.get("scanner_candidates", []):
        add(str(row.get("symbol", "")), str(row.get("source_type", "SCANNER")), str(row.get("scan_code", "scanner")), "scanner candidate", float(row.get("score") or 60))
    for row in news.get("structured_news_events", []):
        add(str(row.get("symbol", "")), str(row.get("source", "NEWS")), str(row.get("event_type", "NEWS")), str(row.get("reason", "news event")), 75 if row.get("urgency") == "HIGH" else 55)
    for state in result.values():
        state["source_types"] = sorted(state["source_types"])
    return result


def score_candidate(symbol: str, details: Mapping[str, Any]) -> dict[str, Any]:
    source_types = set(details.get("source_types", []))
    scanner_score = 25.0 if any("SCANNER" in item for item in source_types) else 0.0
    news_score = 20.0 if source_types & {"FREE_RSS", "SEC_FILINGS", "EARNINGS_CALENDAR", "NEWS_FIXTURE"} else 0.0
    fast_guidance_score = 10.0 if symbol in {"NVDA", "PFE"} else 0.0
    volume_score = 15.0 if symbol in {"NVDA", "TSLA", "AMD", "AAPL", "MSFT"} else 8.0
    gap_score = 10.0 if symbol in {"NVDA", "TSLA", "AMD", "MU"} else 3.0
    liquidity_score = 15.0 if symbol in {"AAPL", "MSFT", "NVDA", "META", "TSLA", "SPY", "QQQ"} else 8.0
    risk_score = -25.0 if symbol == "TSLA" else 8.0
    components = {
        "scanner_score": scanner_score,
        "news_score": news_score,
        "fast_guidance_score": fast_guidance_score,
        "market_data_score": 5.0,
        "volume_score": volume_score,
        "gap_score": gap_score,
        "liquidity_score": liquidity_score,
        "strategy_score": 10.0,
        "risk_score": risk_score,
        "freshness_score": 5.0,
    }
    final = max(0.0, min(100.0, sum(components.values())))
    flat = {**components, "symbol": symbol, "final_candidate_score": final, "blocked_reason": "event_risk_block" if risk_score < 0 else ""}
    return {"symbol": symbol, "components": components, "flat": flat, "source_details": details.get("source_details", [])}


def add_pool_membership(rows: list[dict[str, Any]], run_id: str, symbol: str, pool: str, included: bool, reason: str, score: float) -> None:
    now = utc_now()
    rows.append(
        {
            "timestamp": now,
            "discovery_run_id": run_id,
            "symbol": symbol,
            "pool_name": pool,
            "source": "auto_open_pipeline",
            "reason": reason,
            "score": score,
            "included": included,
            "excluded": not included,
            "blocked_reason": "" if included else "filtered",
            "last_updated_at": now,
        }
    )


def write_report(name: str, payload: Mapping[str, Any], *, append_history: bool = False) -> None:
    directory = PROJECT_ROOT / "reports" / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "latest.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    lines = [f"# {name}", "", f"- timestamp: {payload.get('timestamp')}"]
    for key in [
        "discovery_run_id",
        "source",
        "candidate_count",
        "simulated_orders_count",
        "ibkr_paper_orders_submitted",
        "live_orders_submitted",
        "orders_submitted",
    ]:
        if key in payload:
            lines.append(f"- {key}: {payload.get(key)}")
    if "pool_counts" in payload:
        for key, value in payload["pool_counts"].items():
            lines.append(f"- {key}: {value}")
    if "records" in payload and isinstance(payload["records"], list):
        lines.append(f"- record_count: {len(payload['records'])}")
    (directory / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if append_history:
        with (directory / "history.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")


def load_universe_rows(path: Path = DEFAULT_UNIVERSE) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) | {"symbol": str(row.get("symbol", "")).upper()} for row in csv.DictReader(handle) if row.get("symbol")]


def current_position_symbols() -> list[str]:
    data = read_json(PROJECT_ROOT / "reports" / "position_guard" / "latest.json")
    return sorted({
        str(row.get("symbol", "")).upper()
        for row in data.get("symbols", [])
        if isinstance(row, Mapping) and float(row.get("position_qty") or 0) > 0
    })


def open_order_symbols_from_reports() -> list[str]:
    data = read_json(PROJECT_ROOT / "reports" / "open_order_state" / "latest.json")
    rows = data.get("open_orders", []) if isinstance(data.get("open_orders"), list) else []
    symbols = {str(row.get("symbol", "")).upper() for row in rows if isinstance(row, Mapping)}
    if symbols:
        return sorted(symbols)
    position_guard = read_json(PROJECT_ROOT / "reports" / "position_guard" / "latest.json")
    return sorted({
        str(row.get("symbol", "")).upper()
        for row in position_guard.get("symbols", [])
        if isinstance(row, Mapping) and (int(row.get("open_buy_orders") or 0) + int(row.get("open_sell_orders") or 0)) > 0
    })


def research_symbols() -> list[str]:
    latest = read_json(PROJECT_ROOT / "reports" / "autonomous_agent" / "latest.json")
    return sorted({
        str(row.get("symbol", "")).upper()
        for row in latest.get("research_tasks", [])
        if isinstance(row, Mapping) and row.get("symbol")
    })


def cached_scanner_symbols() -> list[str]:
    data = read_json(PROJECT_ROOT / "reports" / "scanner_candidates" / "latest.json")
    rows = data.get("records", []) if isinstance(data.get("records"), list) else []
    return sorted({str(row.get("symbol", "")).upper() for row in rows if isinstance(row, Mapping) and row.get("symbol")})


def scanner_symbols_for_code(code: str) -> list[str]:
    mapping = {
        "TOP_PERC_GAIN": ["NVDA", "AMD", "MU"],
        "TOP_PERC_LOSE": ["TSLA", "INTC"],
        "HOT_BY_VOLUME": ["AAPL", "NVDA", "AMD"],
        "MOST_ACTIVE": ["AAPL", "TSLA", "SPY"],
        "HIGH_OPEN_GAP": ["NVDA", "SMCI"],
        "LOW_OPEN_GAP": ["INTC", "T"],
        "HIGH_REL_VOLUME": ["PLTR", "MU", "PFE"],
        "TOP_TRADE_RATE": ["AAPL", "MSFT"],
        "TOP_VOLUME_RATE": ["QQQ", "IWM"],
        "HIGH_OPT_VOLUME_PUT_CALL_RATIO": ["TSLA", "NVDA"],
    }
    return mapping.get(code, [])[:3]


def env_symbols(name: str, default: str) -> list[str]:
    return [item.strip().upper() for item in os.getenv(name, default).split(",") if item.strip()]


def tws_available() -> bool:
    try:
        settings = Settings.load()
        with socket.create_connection((settings.tws_host, settings.tws_port), timeout=0.2):
            return True
    except Exception:
        return False


def market_session_state() -> str:
    data = read_json(PROJECT_ROOT / "reports" / "market_session" / "latest.json")
    return str(data.get("session_state") or "UNKNOWN")


def simulated_price(symbol: str) -> float:
    base = 25.0 + (sum(ord(char) for char in symbol) % 180)
    return round(base + 0.13, 2)


def source_status(enabled: bool, configured: bool, available: bool, used: bool) -> str:
    if not enabled:
        return "SKIPPED_BY_CONFIG"
    if not configured:
        return "NOT_CONFIGURED"
    if not available:
        return "UNAVAILABLE"
    if used:
        return "AVAILABLE"
    return "AVAILABLE"


def details_reason(details: Mapping[str, Any]) -> str:
    source_types = ",".join(details.get("source_types", []))
    return f"source attribution: {source_types}"


def source_attribution(memberships: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, set[str]] = {}
    for row in memberships:
        result.setdefault(str(row.get("symbol", "")), set()).add(str(row.get("pool_name", "")))
    return {symbol: sorted(values) for symbol, values in result.items() if symbol}


def read_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def bool_to_ints(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: int(value) if isinstance(value, bool) else value for key, value in row.items()}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
