import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from trading.config import PROJECT_ROOT


REPORT_DIR = PROJECT_ROOT / "reports" / "event_router"


def build_event_router_report(
    *,
    position_guard: Mapping[str, Any] | None = None,
    gap_risk: Mapping[str, Any] | None = None,
    gap_escape: Mapping[str, Any] | None = None,
    event_risk: Mapping[str, Any] | None = None,
    outside_rth: Mapping[str, Any] | None = None,
    pool_membership: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    position_guard = position_guard or read_json(PROJECT_ROOT / "reports" / "position_guard" / "latest.json")
    gap_risk = gap_risk or read_json(PROJECT_ROOT / "reports" / "gap_risk" / "latest.json")
    gap_escape = gap_escape or read_json(PROJECT_ROOT / "reports" / "gap_escape" / "latest.json")
    event_risk = event_risk or read_json(PROJECT_ROOT / "reports" / "event_risk" / "latest.json")
    outside_rth = outside_rth or read_json(PROJECT_ROOT / "reports" / "outside_rth_protection" / "latest.json")
    pool_membership = pool_membership or read_json(PROJECT_ROOT / "reports" / "pool_membership" / "latest.json")
    events = []
    for row in position_guard.get("symbols", []):
        if isinstance(row, Mapping) and row.get("risk_action_needed"):
            events.append(event(now, row.get("symbol"), "position_guard", "trigger_position_guard_review", row.get("recommended_action")))
        if isinstance(row, Mapping) and row.get("stale_quote_warning"):
            events.append(event(now, row.get("symbol"), "market_data", "notify_user", "stale quote"))
        if isinstance(row, Mapping) and row.get("spread_warning"):
            events.append(event(now, row.get("symbol"), "market_data", "notify_user", "spread warning"))
    for report, source, action_key in [
        (gap_risk, "gap_risk", "trigger_gap_risk_review"),
        (gap_escape, "gap_escape", "trigger_gap_escape_review"),
        (event_risk, "event_risk", "block_new_buy_for_symbol"),
        (outside_rth, "outside_rth", "trigger_outside_rth_protection_review"),
    ]:
        for row in report.get("symbols", []):
            if not isinstance(row, Mapping):
                continue
            if row.get("over_budget") or row.get("emergency_action_allowed") or row.get("event_risk_score", 0) >= 0.7 or row.get("needs_STP_LMT_conversion"):
                events.append(event(now, row.get("symbol"), source, action_key, row.get("recommended_action") or row.get("blocked_reason") or "review"))
    for row in pool_membership.get("records", [])[:200]:
        if isinstance(row, Mapping) and row.get("pool_name") == "hot_pool" and row.get("included"):
            events.append(event(now, row.get("symbol"), "pool_membership", "promote_to_hot_pool", row.get("reason")))
    report = {
        "timestamp": now,
        "source": "event_router",
        "report_only": True,
        "submitted_orders": 0,
        "events": events,
        "action_count": len(events),
    }
    write_report(report)
    return report


def event(now: str, symbol: object, source: str, action: str, reason: object) -> dict[str, Any]:
    return {
        "timestamp": now,
        "symbol": str(symbol or "").upper(),
        "event_source": source,
        "recommended_action": action,
        "reason": str(reason or ""),
        "report_only": True,
        "execution_allowed": False,
        "decision_chain": [
            {"step": "source_event_detected", "source": source},
            {"step": "map_to_report_only_action", "recommended_action": action},
            {"step": "execution_allowed", "value": False, "reason": "event_router is report-only"},
        ],
    }


def write_report(report: Mapping[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "latest.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    with (REPORT_DIR / "history.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, sort_keys=True) + "\n")
    lines = ["# Event Router", "", f"- action_count: {report.get('action_count')}", "", "| Symbol | Source | Action | Reason |", "|---|---|---|---|"]
    for row in report.get("events", [])[:200]:
        lines.append(f"| {row.get('symbol')} | {row.get('event_source')} | {row.get('recommended_action')} | {row.get('reason')} |")
    (REPORT_DIR / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
