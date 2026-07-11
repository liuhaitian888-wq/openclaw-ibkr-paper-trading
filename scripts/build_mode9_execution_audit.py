#!/usr/bin/env python3
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


REPORT_PATH = PROJECT_ROOT / "reports" / "mode9_execution_audit" / "latest.json"


def main() -> int:
    latest = _read_json(PROJECT_ROOT / "reports/autonomous_agent/latest.json")
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode9_can_submit_paper_orders": True,
        "mode9_buy_freeze": _bool_env("MODE9_BUY_FREEZE", True),
        "latest_reported_mode9_buy_freeze": latest.get("mode9_buy_freeze"),
        "mode9_standard_process": True,
        "mode9_pid_file": str(PROJECT_ROOT / ".runtime/autonomous_agent.pid"),
        "mode9_pid": _read_text(PROJECT_ROOT / ".runtime/autonomous_agent.pid"),
        "submit_path": [
            "scripts/run_autonomous_trading_agent.py:run_strategy_once",
            "scripts/run_pool_strategy_module.py:submit_order",
            "Trading API /v1/orders/paper/limit",
            "trading/service.py:submit_limit",
            "trading/tws_paper.py:submit_limit",
        ],
        "order_types": {
            "buy_limit_orders": True,
            "sell_limit_orders": True,
            "protective_sell_stp_orders": False,
            "bracket_orders": False,
            "notes": "Mode 9 pool module submits single limit orders through the Trading API. Protective stop orders observed today were produced by the separate autonomous paper runtime before it was stopped.",
        },
        "uses_module_allowed_symbols_as_trading_pool": True,
        "module_allowed_symbols_count": len(latest.get("module_allowed_symbols", [])),
        "module_allowed_symbols": latest.get("module_allowed_symbols", []),
        "monitor_symbols_count": len(latest.get("monitor_symbols", [])),
        "monitor_symbols": latest.get("monitor_symbols", []),
        "protects_existing_account_positions_separately": False,
        "reads_current_positions_before_submit": True,
        "reads_open_orders_before_submit": True,
        "runs_position_guard_before_strategy": True,
        "runs_position_protection_before_strategy": True,
        "current_limitations": [
            "Mode 9 in-memory module positions are not the same as IBKR account positions.",
            "Position protection repair is disabled unless POSITION_PROTECTION_REPAIR_ENABLED=true.",
            "Held symbols are monitored even if they are not buy-eligible.",
        ],
        "latest_agent_created_at": latest.get("created_at"),
        "latest_strategy_run": latest.get("strategy_run"),
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _read_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
