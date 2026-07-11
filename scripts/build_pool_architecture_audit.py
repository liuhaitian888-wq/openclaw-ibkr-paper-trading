#!/usr/bin/env python3
"""Audit whether the six-layer pool architecture is implemented and wired."""

import csv
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


ARCH_DIR = PROJECT_ROOT / "reports" / "pool_architecture"
MEMBERSHIP_DIR = PROJECT_ROOT / "reports" / "pool_membership"
AUDIT_DIR = PROJECT_ROOT / "reports" / "pool_audit"
LAYERS = [
    "security_master",
    "discovery_universe",
    "tradable_universe",
    "stream_eligible_pool",
    "monitor_pool",
    "hot_pool",
    "trade_pool",
]


def main() -> int:
    architecture, membership, audit = build_reports()
    write_outputs(architecture, membership, audit)
    print(json.dumps({"architecture": architecture, "audit": audit}, indent=2, sort_keys=True))
    return 0


def build_reports() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat()
    files = {
        "security_master_py": PROJECT_ROOT / "trading" / "security_master.py",
        "pool_manager_py": PROJECT_ROOT / "trading" / "pool_manager.py",
        "event_router_py": PROJECT_ROOT / "trading" / "event_router.py",
        "universe_csv": PROJECT_ROOT / "data" / "us_equity_universe.csv",
        "mode9": PROJECT_ROOT / "scripts" / "run_autonomous_trading_agent.py",
        "strategy_module": PROJECT_ROOT / "scripts" / "run_pool_strategy_module.py",
    }
    latest_agent = read_json(PROJECT_ROOT / "reports" / "autonomous_agent" / "latest.json")
    position_guard = read_json(PROJECT_ROOT / "reports" / "position_guard" / "latest.json")
    universe_rows = read_universe(files["universe_csv"])
    mode9_source = files["mode9"].read_text(encoding="utf-8") if files["mode9"].exists() else ""
    strategy_source = files["strategy_module"].read_text(encoding="utf-8") if files["strategy_module"].exists() else ""
    held = sorted({
        str(row.get("symbol", "")).upper()
        for row in position_guard.get("symbols", [])
        if isinstance(row, dict) and float(row.get("position_qty") or 0) > 0
    })
    module_allowed = list(latest_agent.get("module_allowed_symbols") or [])
    monitor_symbols = list(latest_agent.get("monitor_symbols") or [])
    universe_symbols = [row["symbol"] for row in universe_rows if row.get("enabled", "true").lower() == "true"]

    security_master_exists = files["security_master_py"].exists()
    pool_manager_exists = files["pool_manager_py"].exists()
    event_router_exists = files["event_router_py"].exists()
    persistent_security_master = security_master_exists or any((PROJECT_ROOT / path).exists() for path in ["data/security_master.csv", "data/security_master.json", "security_master.sqlite3", "reports/security_master/latest.json"])
    persistent_pool_files = list((PROJECT_ROOT / "reports").glob("pool_membership/*.json")) + list((PROJECT_ROOT / "data").glob("*pool*"))

    layers = [
        layer_report(
            name="security_master",
            implemented=persistent_security_master,
            execution_active=False,
            source_files=[str(files["security_master_py"])] if security_master_exists else [],
            data_sources=[],
            symbols=[],
            missing=["trading/security_master.py", "persistent security master table/file"] if not persistent_security_master else [],
            next_step="Create security master store and symbol identity schema.",
        ),
        layer_report("discovery_universe", False, False, [], ["scanner/news/SEC/Nasdaq documented only"], [], ["connected discovery ingestion"], "Wire scanner/news/SEC/Nasdaq sources."),
        layer_report("tradable_universe", True, False, [str(files["universe_csv"]), str(files["mode9"])], ["data/us_equity_universe.csv", "Trading API allowlist", "value filter"], module_allowed or universe_symbols, [], "Keep reporting; execution still uses legacy CSV/module_allowed path."),
        layer_report("stream_eligible_pool", pool_manager_exists, False, ["trading/market_data_line_manager.py", str(files["pool_manager_py"])], ["pool_manager report-only candidates"], [], ["execution consumption"], "Wire stream eligibility after pool reports are stable."),
        layer_report("monitor_pool", True, False, [str(files["mode9"]), str(files["pool_manager_py"])], ["current positions + selected universe"], monitor_symbols, [], "Persist monitor_pool membership with reasons."),
        layer_report("hot_pool", pool_manager_exists or event_router_exists, False, [str(files["pool_manager_py"]), str(files["event_router_py"])], ["top_movers/research_tasks transient only"], [str(task.get("symbol")) for task in latest_agent.get("research_tasks", [])[:8] if isinstance(task, dict)], ["execution consumption"], "Promote transient movers into audited hot_pool."),
        layer_report("trade_pool", True, False, [str(files["strategy_module"]), str(files["pool_manager_py"])], ["module_allowed_symbols", "strategy decisions"], module_allowed, ["not execution source from pool_manager yet"], "Make trade_pool a persisted pool_manager output after report-only validation."),
    ]

    membership_rows = membership_records(now, universe_rows, monitor_symbols, module_allowed, held)
    answers = {
        "trading/security_master.py exists": security_master_exists,
        "trading/pool_manager.py exists": pool_manager_exists,
        "trading/event_router.py exists": event_router_exists,
        "persistent security_master exists": persistent_security_master,
        "persistent membership for each pool exists": False,
        "membership schema complete": membership_schema_complete(membership_rows),
        "current positions included in monitor_pool and risk monitoring": all(symbol in monitor_symbols for symbol in held),
        "hard_coded_production_symbol_lists_removed": False,
        "hard_coded_symbols_limited_to_tests_audits_examples": False,
        "Mode 9 refreshes pool_manager report": "build_pool_manager_report" in mode9_source,
        "Mode 9 consumes pool_manager output": False,
        "Mode 9 consumes pool_manager output for execution": False,
        "Mode 9 uses data/us_equity_universe.csv directly": "load_universe" in mode9_source and "universe_file" in mode9_source,
        "Mode 9 relies on module_allowed_symbols": "module_allowed_symbols" in mode9_source,
        "scanner/news/SEC/Nasdaq sources connected": False,
        "six_layer_system_state": "report-only implemented; Mode 9 refreshes reports but does not use pool_manager as execution symbol source",
        "real_source_of_trading_symbols": "data/us_equity_universe.csv filtered into module_allowed_symbols plus current held positions forced into monitor_symbols",
    }
    architecture = {
        "timestamp": now,
        "source": "pool_architecture_audit",
        "summary": "Six-layer pool architecture is not fully implemented and not wired into Mode 9 as pool_manager output.",
        "layers": layers,
        "answers": answers,
    }
    membership = {
        "timestamp": now,
        "source": "pool_membership_audit",
        "schema_fields": ["symbol", "pool_name", "source", "reason", "score", "included", "excluded", "blocked_reason", "last_updated_at"],
        "records": membership_rows,
    }
    audit = {
        "timestamp": now,
        "source": "pool_audit",
        "files_checked": {key: str(value) for key, value in files.items()},
        "file_exists": {key: value.exists() for key, value in files.items()},
        "sqlite_tables": sqlite_tables(PROJECT_ROOT / "trading_audit.sqlite3"),
        "persistent_pool_files": [str(path) for path in persistent_pool_files],
        "answers": answers,
    }
    return architecture, membership, audit


def layer_report(name: str, implemented: bool, execution_active: bool, source_files: list[str], data_sources: list[str], symbols: list[str], missing: list[str], next_step: str) -> dict[str, Any]:
    return {
        "pool_name": name,
        "implemented": implemented,
        "report_only": implemented and not execution_active,
        "execution_active": execution_active,
        "source_files": source_files,
        "data_sources": data_sources,
        "symbol_count": len(set(symbols)),
        "example_symbols": list(dict.fromkeys(symbols))[:10],
        "missing_components": missing,
        "next_steps": next_step,
    }


def membership_records(now: str, universe_rows: list[dict[str, str]], monitor: list[str], trade: list[str], held: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in universe_rows:
        included = row.get("enabled", "true").lower() == "true"
        records.append(record(row["symbol"], "tradable_universe", "data/us_equity_universe.csv", "enabled universe row", None, included, not included, "disabled" if not included else "", now))
    for symbol in monitor:
        reason = "current held position forced into monitor_pool" if symbol in held else "selected universe monitor symbol"
        records.append(record(symbol, "monitor_pool", "Mode 9 latest.json", reason, None, True, False, "", now))
    for symbol in trade:
        records.append(record(symbol, "trade_pool", "module_allowed_symbols", "value-approved module allowed symbol", None, True, False, "", now))
    return records


def record(symbol: str, pool_name: str, source: str, reason: str, score: float | None, included: bool, excluded: bool, blocked_reason: str, now: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "pool_name": pool_name,
        "source": source,
        "reason": reason,
        "score": score,
        "included": included,
        "excluded": excluded,
        "blocked_reason": blocked_reason,
        "last_updated_at": now,
    }


def write_outputs(architecture: dict[str, Any], membership: dict[str, Any], audit: dict[str, Any]) -> None:
    ARCH_DIR.mkdir(parents=True, exist_ok=True)
    MEMBERSHIP_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    (ARCH_DIR / "latest.json").write_text(json.dumps(architecture, indent=2, sort_keys=True), encoding="utf-8")
    (MEMBERSHIP_DIR / "latest.json").write_text(json.dumps(membership, indent=2, sort_keys=True), encoding="utf-8")
    with (MEMBERSHIP_DIR / "history.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(membership, sort_keys=True) + "\n")
    (AUDIT_DIR / "latest.json").write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")
    (ARCH_DIR / "latest.md").write_text(markdown(architecture), encoding="utf-8")


def markdown(architecture: dict[str, Any]) -> str:
    lines = ["# Pool Architecture Audit", "", architecture["summary"], "", "## Answers"]
    for key, value in architecture["answers"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Layers", "", "| Pool | Implemented | Report Only | Execution Active | Symbols | Missing | Next |", "|---|---:|---:|---:|---:|---|---|"])
    for layer in architecture["layers"]:
        lines.append(
            f"| {layer['pool_name']} | {layer['implemented']} | {layer['report_only']} | {layer['execution_active']} | "
            f"{layer['symbol_count']} | {', '.join(layer['missing_components']) or 'none'} | {layer['next_steps']} |"
        )
    return "\n".join(lines) + "\n"


def read_universe(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def sqlite_tables(path: Path) -> list[str]:
    if not path.exists():
        return []
    with sqlite3.connect(path) as con:
        return [row[0] for row in con.execute("select name from sqlite_master where type='table' order by name")]


def membership_schema_complete(records: list[dict[str, Any]]) -> bool:
    required = {"symbol", "pool_name", "source", "reason", "score", "included", "excluded", "blocked_reason", "last_updated_at"}
    return bool(records) and all(required.issubset(record) for record in records)


if __name__ == "__main__":
    raise SystemExit(main())
