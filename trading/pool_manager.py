import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from trading.config import PROJECT_ROOT
from trading.security_master import DEFAULT_SECURITY_MASTER, build_security_master_report
from trading.universe import load_universe, select_universe, UniverseSelectionConfig
from trading.strategy import ValueFilterConfig, ValuePoolFilter


ARCH_DIR = PROJECT_ROOT / "reports" / "pool_architecture"
MEMBERSHIP_DIR = PROJECT_ROOT / "reports" / "pool_membership"
AUDIT_DIR = PROJECT_ROOT / "reports" / "pool_audit"
DEFAULT_UNIVERSE = PROJECT_ROOT / "data" / "us_equity_universe.csv"


@dataclass(frozen=True)
class PoolMembership:
    timestamp: str
    symbol: str
    pool_name: str
    included: bool
    excluded: bool
    source: str
    reason: str
    score: float | None
    blocked_reason: str
    last_updated_at: str


def build_pool_manager_report(
    *,
    universe_file: Path = DEFAULT_UNIVERSE,
    security_master_file: Path = DEFAULT_SECURITY_MASTER,
    position_guard: Mapping[str, Any] | None = None,
    latest_agent: Mapping[str, Any] | None = None,
    max_symbols: int = 60,
    min_value_score: float = 45.0,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    security_master = build_security_master_report(universe_file, security_master_file=security_master_file)
    position_guard = dict(position_guard or read_json(PROJECT_ROOT / "reports" / "position_guard" / "latest.json"))
    latest_agent = dict(latest_agent or read_json(PROJECT_ROOT / "reports" / "autonomous_agent" / "latest.json"))
    held_symbols = sorted({
        str(row.get("symbol", "")).upper()
        for row in position_guard.get("symbols", [])
        if isinstance(row, Mapping) and float(row.get("position_qty") or 0) > 0
    })
    open_order_symbols = sorted({
        str(row.get("symbol", "")).upper()
        for row in position_guard.get("symbols", [])
        if isinstance(row, Mapping) and (int(row.get("open_buy_orders") or 0) + int(row.get("open_sell_orders") or 0)) > 0
    })
    value_filter = ValuePoolFilter(ValueFilterConfig(min_score=min_value_score))
    selection = select_universe(
        load_universe(universe_file),
        value_filter,
        UniverseSelectionConfig(max_symbols=max_symbols),
    )
    memberships: list[PoolMembership] = []
    add = lambda symbol, pool, included, source, reason, score=None, blocked="": memberships.append(
        PoolMembership(now, symbol, pool, included, not included, source, reason, score, blocked, now)
    )
    for row in security_master["records"]:
        security_included = not bool(row.get("blocked_reason"))
        discovery_included, discovery_blocked = discovery_eligibility(row)
        add(row["symbol"], "security_master", security_included, row.get("data_source") or "security_master", "global security master", None, row.get("blocked_reason", ""))
        add(row["symbol"], "discovery_universe", discovery_included, "security_master", "hard instrument eligibility", None, discovery_blocked)
    for record in selection.records:
        symbol = str(record["symbol"])
        included = bool(record.get("approved"))
        blocked = "; ".join(str(item) for item in record.get("reasons", []))
        add(symbol, "tradable_universe", included, "value_filter", "value and allowlist filter", record.get("score"), blocked)
        if included:
            add(symbol, "stream_eligible_pool", True, "tradable_universe", "report-only stream candidate", record.get("score"))
            add(symbol, "trade_pool", True, "module_allowed_symbols equivalent", "report-only trade candidate", record.get("score"))
    monitor = list(dict.fromkeys([*held_symbols, *open_order_symbols, *latest_agent.get("monitor_symbols", [])]))
    for symbol in monitor:
        reason = "held/open-order symbol forced into monitor_pool" if symbol in set(held_symbols) | set(open_order_symbols) else "Mode 9 monitor symbol"
        add(symbol, "monitor_pool", True, "positions/open_orders/mode9", reason)
    for task in latest_agent.get("research_tasks", []):
        if isinstance(task, Mapping) and task.get("symbol"):
            add(str(task["symbol"]).upper(), "hot_pool", True, "research_tasks", str(task.get("reason") or "top mover"))
    architecture = architecture_report(now, memberships)
    membership_report = {"timestamp": now, "source": "pool_manager", "report_only": True, "records": [asdict(item) for item in memberships]}
    audit = {
        "timestamp": now,
        "source": "pool_manager_audit",
        "report_only": True,
        "execution_active": False,
        "mode9_trading_source_unchanged": True,
        "global_security_master_count": len({row["symbol"] for row in security_master["records"]}),
        "security_master_source_mode": security_master.get("source_mode"),
        "current_positions_forced_into_monitor_pool": held_symbols,
        "open_orders_forced_into_monitor_pool": open_order_symbols,
        "blocked_symbols": [asdict(item) for item in memberships if item.excluded],
    }
    write_reports(architecture, membership_report, audit)
    return {
        **architecture,
        "report_only": True,
        "architecture": architecture,
        "membership": membership_report,
        "audit": audit,
    }


def discovery_eligibility(row: Mapping[str, Any]) -> tuple[bool, str]:
    if row.get("blocked_reason"):
        return False, str(row.get("blocked_reason"))
    if row.get("asset_type") not in {"STK", "ETF"}:
        return False, "UNSUPPORTED_SECURITY_TYPE"
    if row.get("currency") != "USD":
        return False, "UNSUPPORTED_CURRENCY"
    if row.get("is_otc"):
        return False, "OTC_NOT_ALLOWED"
    if row.get("is_test_issue"):
        return False, "TEST_ISSUE"
    if str(row.get("listing_status") or "").lower() not in {"", "active"}:
        return False, "SYMBOL_NOT_ACTIVE"
    return True, ""


def architecture_report(now: str, memberships: list[PoolMembership]) -> dict[str, Any]:
    layers = []
    for pool in ["security_master", "discovery_universe", "tradable_universe", "stream_eligible_pool", "monitor_pool", "hot_pool", "trade_pool"]:
        rows = [item for item in memberships if item.pool_name == pool and item.included]
        layers.append({
            "pool_name": pool,
            "implemented": True,
            "report_only": True,
            "execution_active": False,
            "connected_to_mode9": True,
            "symbol_count": len({item.symbol for item in rows}),
            "source": sorted({item.source for item in rows}),
            "example_symbols": list(dict.fromkeys(item.symbol for item in rows))[:10],
            "blocked_reason": "report-only; not an execution authorization source",
            "remaining_gap": "wire explicit strategy signal/risk approval into canonical L5 gate" if pool == "trade_pool" else "",
        })
    return {
        "timestamp": now,
        "source": "pool_manager",
        "classification": "B+) wired into Mode 9 monitoring/state; execution authorization remains gated",
        "summary": "Six-layer pools feed Mode 9 monitoring and canonical state. Paper execution still requires explicit strategy, quote, session, risk, and account gates.",
        "layers": layers,
    }


def write_reports(architecture: Mapping[str, Any], membership: Mapping[str, Any], audit: Mapping[str, Any]) -> None:
    ARCH_DIR.mkdir(parents=True, exist_ok=True)
    MEMBERSHIP_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    (ARCH_DIR / "latest.json").write_text(json.dumps(architecture, indent=2, sort_keys=True), encoding="utf-8")
    (MEMBERSHIP_DIR / "latest.json").write_text(json.dumps(membership, indent=2, sort_keys=True), encoding="utf-8")
    with (MEMBERSHIP_DIR / "history.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(membership, sort_keys=True) + "\n")
    (AUDIT_DIR / "latest.json").write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")
    lines = ["# Pool Architecture", "", architecture["summary"], "", "| Pool | Symbols | Connected | Execution | Remaining |", "|---|---:|---:|---:|---|"]
    for row in architecture["layers"]:
        lines.append(f"| {row['pool_name']} | {row['symbol_count']} | {row['connected_to_mode9']} | {row['execution_active']} | {row['remaining_gap']} |")
    (ARCH_DIR / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
