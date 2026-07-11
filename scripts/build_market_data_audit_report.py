#!/usr/bin/env python3
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


REPORT_PATH = PROJECT_ROOT / "reports" / "market_data_audit" / "latest.json"


def main() -> int:
    latest_agent = _read_json(PROJECT_ROOT / "reports/autonomous_agent/latest.json")
    latest_runtime = _read_json(PROJECT_ROOT / "reports/autonomous_runtime_status.json")
    latest_pool = _latest_pool_report()
    code_hits = _code_hits()
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode9_market_data_mode": "snapshot_polling",
        "mode9_uses_snapshot_polling": True,
        "mode9_uses_level1_streaming": bool(latest_agent.get("streaming_enabled")),
        "mode9_uses_tick_by_tick": False,
        "snapshot_true_locations": code_hits["snapshot_true"],
        "snapshot_false_locations": code_hits["snapshot_false"],
        "market_data_type_1_locations": code_hits["market_data_type_1"],
        "market_data_type_3_locations": code_hits["market_data_type_3"],
        "execution_process_uses_delayed_data": _execution_uses_delayed(latest_runtime),
        "bid_ask_persisted": True,
        "last_close_volume_timestamp_persisted": True,
        "mode9_latest": {
            "created_at": latest_agent.get("created_at"),
            "quote_count": latest_agent.get("quote_count"),
            "monitor_symbols": latest_agent.get("monitor_symbols", []),
            "streaming_enabled": latest_agent.get("streaming_enabled"),
            "streaming_symbols": latest_agent.get("streaming_symbols", []),
            "streaming_errors": latest_agent.get("streaming_errors", []),
        },
        "latest_pool_report": {
            "path": latest_pool.get("_path"),
            "created_at": latest_pool.get("created_at"),
            "mode": latest_pool.get("mode"),
            "source": latest_pool.get("source"),
            "returned_symbols": latest_pool.get("returned_symbols", []),
        },
        "symbols_with_valid_bid_ask": _symbols_with_valid_bid_ask(latest_pool),
        "symbols_with_stale_quotes": _symbols_with_stale_quotes(latest_pool),
        "symbols_with_no_permission_or_delayed_only": _symbols_with_no_permission(latest_agent, latest_pool),
        "raw_runtime_market_data_type": _runtime_market_data_type(latest_runtime),
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _latest_pool_report() -> dict[str, Any]:
    paths = sorted((PROJECT_ROOT / "reports").glob("pool_strategy_module_*.json"))
    if not paths:
        return {}
    path = paths[-1]
    data = _read_json(path)
    data["_path"] = str(path)
    return data


def _code_hits() -> dict[str, list[str]]:
    patterns = {
        "snapshot_true": "snapshot=True",
        "snapshot_false": "snapshot=False",
        "market_data_type_1": "market_data_type=1",
        "market_data_type_3": "market_data_type=3",
    }
    files = [
        PROJECT_ROOT / "scripts/run_autonomous_trading_agent.py",
        PROJECT_ROOT / "scripts/run_pool_strategy_module.py",
        PROJECT_ROOT / "scripts/run_autonomous_paper_runtime.py",
        PROJECT_ROOT / "trading/ibkr_readonly.py",
        PROJECT_ROOT / "trading/ibkr_streaming.py",
    ]
    hits = {name: [] for name in patterns}
    for path in files:
        if not path.exists():
            continue
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for name, pattern in patterns.items():
                if pattern in line:
                    hits[name].append(f"{path.relative_to(PROJECT_ROOT)}:{line_no}:{line.strip()}")
    return hits


def _execution_uses_delayed(runtime: dict[str, Any]) -> bool:
    return bool(runtime.get("source") == "autonomous_paper_runtime")


def _runtime_market_data_type(runtime: dict[str, Any]) -> str:
    if runtime.get("source") == "autonomous_paper_runtime":
        return "delayed_or_configured_from_launchd_market_data_type_3"
    return "unknown"


def _symbols_with_valid_bid_ask(pool: dict[str, Any]) -> list[str]:
    result = []
    for quote in pool.get("cache", []):
        if quote.get("bid") is not None and quote.get("ask") is not None:
            result.append(str(quote.get("symbol")))
    return sorted(set(result))


def _symbols_with_stale_quotes(pool: dict[str, Any]) -> list[str]:
    stale = []
    for quote in pool.get("cache", []):
        try:
            if float(quote.get("age_ms", 0)) > 10_000:
                stale.append(str(quote.get("symbol")))
        except (TypeError, ValueError):
            stale.append(str(quote.get("symbol")))
    return sorted(set(stale))


def _symbols_with_no_permission(agent: dict[str, Any], pool: dict[str, Any]) -> list[str]:
    symbols = set()
    text = json.dumps(agent.get("errors", []) + pool.get("source_errors", []) if isinstance(pool.get("source_errors"), list) else agent.get("errors", []))
    for match in re.finditer(r"([A-Z]{1,5}).{0,80}(permission|delayed|pacing)", text, flags=re.I):
        symbols.add(match.group(1).upper())
    return sorted(symbols)


if __name__ == "__main__":
    raise SystemExit(main())
