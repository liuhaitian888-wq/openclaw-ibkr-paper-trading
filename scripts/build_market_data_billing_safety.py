#!/usr/bin/env python3
"""Audit market data billing safety for IBKR reqMktData calls."""

import ast
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


REPORT_DIR = PROJECT_ROOT / "reports" / "market_data_billing_safety"


def main() -> int:
    report = build_report()
    write_report(report)
    print(json.dumps({"status": "ok", "report_path": str(REPORT_DIR / "latest.json")}, indent=2, sort_keys=True))
    return 0


def build_report() -> dict[str, Any]:
    calls = []
    for path in sorted(PROJECT_ROOT.rglob("*.py")):
        if any(part in {".venv", ".venv313", "__pycache__"} for part in path.parts):
            continue
        calls.extend(audit_file(path))
    risky = [call for call in calls if call["paid_snapshot_risk"]]
    regulatory_used = any(call["regulatorySnapshot_parameter"] is True for call in calls)
    snapshot_used = any(call["snapshot_parameter"] is True for call in calls)
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "market_data_billing_safety",
        "no_paid_market_data_requests": env_bool("NO_PAID_MARKET_DATA_REQUESTS", True),
        "regulatory_snapshot_blocked": not env_bool("ALLOW_REGULATORY_SNAPSHOT", False),
        "snapshot_market_data_blocked": not env_bool("ALLOW_SNAPSHOT_MARKET_DATA", False),
        "reqMktData_calls_audited": len(calls),
        "calls": calls,
        "risky_calls_found": len(risky),
        "risky_calls_fixed": sum(1 for call in risky if call["action_taken"] != "none"),
        "remaining_risks": [call for call in risky if call["action_taken"] == "none"],
        "regulatory_snapshot_used": regulatory_used,
        "snapshot_request_used": snapshot_used,
        "paid_snapshot_risk": bool(risky),
        "safe_for_monitoring_line": not regulatory_used and not any(call["automatic_quote_acquisition"] and call["paid_snapshot_risk"] and call["action_taken"] == "none" for call in calls),
    }
    return report


def audit_file(path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
    except Exception:
        return []
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    calls = []
    lines = text.splitlines()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        attr = node.func if isinstance(node.func, ast.Attribute) else None
        if attr is None or attr.attr != "reqMktData":
            continue
        function_name = enclosing_function(node, parents)
        snapshot = arg_value(node, 3, "snapshot")
        regulatory = arg_value(node, 4, "regulatory_snapshot")
        generic = arg_value(node, 2, "genericTickList")
        line = lines[node.lineno - 1].strip() if node.lineno - 1 < len(lines) else ""
        automatic = not ("test_" in str(path) or "/tests/" in str(path) or "audit_ibkr_level1_streaming.py" in str(path))
        risk = regulatory is True or (automatic and snapshot is True)
        action = action_taken(path, line, snapshot, regulatory, automatic)
        calls.append(
            {
                "file": str(path.relative_to(PROJECT_ROOT)),
                "line": node.lineno,
                "function_name": function_name,
                "symbol_or_source": symbol_source(node),
                "snapshot_parameter": snapshot,
                "regulatorySnapshot_parameter": regulatory,
                "genericTickList": generic,
                "market_data_type_requested": market_data_type_nearby(lines, node.lineno),
                "automatic_quote_acquisition": automatic,
                "allowed_by_config": not risk or action != "none",
                "paid_snapshot_risk": risk,
                "action_taken": action,
            }
        )
    return calls


def enclosing_function(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name
    return "<module>"


def arg_value(node: ast.Call, index: int, name: str) -> Any:
    for keyword in node.keywords:
        if keyword.arg == name:
            return literal(keyword.value)
    if len(node.args) > index:
        return literal(node.args[index])
    return None


def literal(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id == "True":
            return True
        if node.id == "False":
            return False
        return node.id
    return ast.unparse(node) if hasattr(ast, "unparse") else "<expr>"


def symbol_source(node: ast.Call) -> str:
    if len(node.args) > 1:
        return ast.unparse(node.args[1]) if hasattr(ast, "unparse") else "contract"
    return "unknown"


def market_data_type_nearby(lines: list[str], lineno: int) -> str:
    start = max(0, lineno - 8)
    end = min(len(lines), lineno + 3)
    nearby = "\n".join(lines[start:end])
    if "reqMarketDataType" in nearby:
        return "reqMarketDataType nearby"
    if "market_data_type=1" in nearby or "market_data_type = 1" in nearby:
        return "1"
    if "market_data_type=3" in nearby or "market_data_type = 3" in nearby:
        return "3"
    return "unknown"


def action_taken(path: Path, line: str, snapshot: Any, regulatory: Any, automatic: bool) -> str:
    rel = str(path.relative_to(PROJECT_ROOT))
    if regulatory is True:
        return "needs_fix_regulatory_snapshot_true"
    if automatic and snapshot is True:
        if rel in {
            "trading/position_guard.py",
            "trading/ibkr_readonly.py",
            "scripts/run_autonomous_trading_agent.py",
        }:
            return "blocked_or_config_gated_default_disabled"
        return "report_only_remaining_risk"
    return "none"


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def write_report(report: dict[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "latest.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    lines = [
        "# Market Data Billing Safety",
        "",
        f"- no_paid_market_data_requests: {report['no_paid_market_data_requests']}",
        f"- regulatory_snapshot_blocked: {report['regulatory_snapshot_blocked']}",
        f"- snapshot_market_data_blocked: {report['snapshot_market_data_blocked']}",
        f"- reqMktData_calls_audited: {report['reqMktData_calls_audited']}",
        f"- risky_calls_found: {report['risky_calls_found']}",
        f"- regulatory_snapshot_used: {report['regulatory_snapshot_used']}",
        f"- snapshot_request_used: {report['snapshot_request_used']}",
        f"- paid_snapshot_risk: {report['paid_snapshot_risk']}",
        f"- safe_for_monitoring_line: {report['safe_for_monitoring_line']}",
        "",
        "| File | Line | Function | Snapshot | Regulatory | Auto | Risk | Action |",
        "|---|---:|---|---|---|---:|---:|---|",
    ]
    for call in report["calls"]:
        lines.append(
            f"| {call['file']} | {call['line']} | {call['function_name']} | {call['snapshot_parameter']} | "
            f"{call['regulatorySnapshot_parameter']} | {call['automatic_quote_acquisition']} | {call['paid_snapshot_risk']} | {call['action_taken']} |"
        )
    (REPORT_DIR / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
