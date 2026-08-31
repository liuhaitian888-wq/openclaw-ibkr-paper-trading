"""Audit whether real IBKR callbacks are wired into RealtimeAccountStateBus."""

from __future__ import annotations

import json
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trading.config import PROJECT_ROOT, Settings


CALLBACKS = [
    "tickPrice",
    "tickSize",
    "tickString",
    "tickGeneric",
    "marketDataType",
    "tickReqParams",
    "tickSnapshotEnd",
    "updateAccountValue",
    "updatePortfolio",
    "updateAccountTime",
    "accountDownloadEnd",
    "position",
    "positionEnd",
    "pnl",
    "pnlSingle",
    "openOrder",
    "openOrderEnd",
    "orderStatus",
    "execDetails",
    "execDetailsEnd",
    "commissionReport",
    "error",
    "connectionClosed",
    "nextValidId",
]

SOURCE_MODULES = {
    "tickPrice": ["trading/ibkr_callback_bridge.py", "trading/ibkr_streaming.py", "trading/ibkr_readonly.py", "scripts/audit_ibkr_level1_streaming.py"],
    "tickSize": ["trading/ibkr_callback_bridge.py", "trading/ibkr_streaming.py", "trading/ibkr_readonly.py", "scripts/audit_ibkr_level1_streaming.py"],
    "tickString": ["trading/ibkr_callback_bridge.py", "trading/ibkr_streaming.py"],
    "tickGeneric": ["trading/ibkr_callback_bridge.py"],
    "marketDataType": ["trading/ibkr_callback_bridge.py", "trading/ibkr_streaming.py"],
    "tickReqParams": ["trading/ibkr_callback_bridge.py"],
    "tickSnapshotEnd": ["trading/ibkr_readonly.py"],
    "updateAccountValue": ["trading/ibkr_callback_bridge.py"],
    "updatePortfolio": ["trading/ibkr_callback_bridge.py", "trading/position_guard.py", "scripts/record_account_pnl.py"],
    "updateAccountTime": ["trading/ibkr_callback_bridge.py"],
    "accountDownloadEnd": ["trading/ibkr_callback_bridge.py", "trading/position_guard.py"],
    "position": ["trading/ibkr_callback_bridge.py"],
    "positionEnd": ["trading/ibkr_callback_bridge.py"],
    "pnl": ["trading/ibkr_callback_bridge.py", "scripts/record_account_pnl.py"],
    "pnlSingle": ["trading/ibkr_callback_bridge.py"],
    "openOrder": ["trading/ibkr_callback_bridge.py", "trading/tws_paper.py", "scripts/list_tws_orders.py"],
    "openOrderEnd": ["trading/ibkr_callback_bridge.py", "trading/tws_paper.py"],
    "orderStatus": ["trading/ibkr_callback_bridge.py", "trading/tws_paper.py", "scripts/list_tws_orders.py"],
    "execDetails": ["trading/ibkr_callback_bridge.py", "scripts/list_tws_orders.py"],
    "execDetailsEnd": ["trading/ibkr_callback_bridge.py"],
    "commissionReport": ["trading/ibkr_callback_bridge.py"],
    "error": [
        "trading/ibkr_callback_bridge.py",
        "trading/ibkr_streaming.py",
        "trading/position_guard.py",
        "trading/tws_paper.py",
        "scripts/record_account_pnl.py",
        "scripts/list_tws_orders.py",
    ],
    "connectionClosed": ["trading/ibkr_callback_bridge.py"],
    "nextValidId": ["trading/ibkr_callback_bridge.py"],
}

EVENT_TYPES = {
    "tickPrice": "quote_state_events",
    "tickSize": "quote_state_events",
    "tickString": "quote_state_events",
    "tickGeneric": "quote_state_events",
    "marketDataType": "quote_state_events",
    "tickReqParams": "quote_state_events",
    "tickSnapshotEnd": "quote_state_events",
    "updateAccountValue": "account_state_events",
    "updatePortfolio": "position_state_events",
    "updateAccountTime": "account_state_events",
    "accountDownloadEnd": "account_state_events",
    "position": "position_state_events",
    "positionEnd": "position_state_events",
    "pnl": "pnl_state_events",
    "pnlSingle": "pnl_state_events",
    "openOrder": "open_order_state_events",
    "openOrderEnd": "open_order_state_events",
    "orderStatus": "open_order_state_events",
    "execDetails": "execution_state_events",
    "execDetailsEnd": "execution_state_events",
    "commissionReport": "execution_state_events",
    "error": "risk_state_events",
    "connectionClosed": "risk_state_events",
    "nextValidId": "risk_state_events",
}

REPORT_DIR = PROJECT_ROOT / "reports" / "ibkr_callback_wiring"


def build_ibkr_callback_wiring_audit() -> dict[str, Any]:
    now = utc_now()
    bus = read_json(PROJECT_ROOT / "reports" / "realtime_account_state_bus" / "latest.json")
    sync = read_json(PROJECT_ROOT / "reports" / "realtime_account_sync" / "latest.json")
    freshness = read_json(PROJECT_ROOT / "reports" / "state_freshness_policy" / "latest.json")
    market = read_json(PROJECT_ROOT / "reports" / "market_session" / "latest.json")
    streaming = read_json(PROJECT_ROOT / "reports" / "streaming_quote_diagnostics" / "latest.json")
    ibkr_connected = tws_socket_available()
    dry_run = read_json(PROJECT_ROOT / "reports" / "ibkr_callback_dry_run" / "latest.json")
    callback_rows = [callback_row(name, bus, dry_run) for name in CALLBACKS]
    callbacks_registered = any(row["callback_registered"] for row in callback_rows)
    ask_fresh = "stale_ask" not in freshness.get("blocked_reasons", [])
    bid_fresh = "stale_bid" not in freshness.get("blocked_reasons", [])
    last_fresh = not bool(freshness.get("blocked_reasons"))
    market_closed = market.get("expected_live_bid_ask") is False or market.get("session_state") in {"CLOSED", "OVERNIGHT"}
    quote_execution_ready = bool(ask_fresh and bid_fresh and not market_closed)
    blocked_reason = "" if quote_execution_ready else "stale_ask_or_market_closed" if not ask_fresh or market_closed else "quote_not_ready"
    report = {
        "timestamp": now,
        "source": "ibkr_callback_wiring_audit",
        "strict_safety": {
            "live_trading_enabled": False,
            "ibkr_paper_orders_submitted": 0,
            "live_orders_submitted": 0,
            "orders_cancelled": 0,
            "paid_snapshot_used": False,
            "regulatory_snapshot_used": False,
            "market_order_used": False,
        },
        "bus_running": bool(bus),
        "bus_ok": bool(bus),
        "ibkr_connected": ibkr_connected,
        "callbacks_registered": callbacks_registered,
        "account_callbacks_wired": callback_wired(callback_rows, {"updateAccountValue", "updateAccountTime", "accountDownloadEnd"}),
        "position_callbacks_wired": callback_wired(callback_rows, {"updatePortfolio", "position", "positionEnd"}),
        "pnl_callbacks_wired": callback_wired(callback_rows, {"pnl", "pnlSingle"}),
        "order_callbacks_wired": callback_wired(callback_rows, {"openOrder", "orderStatus"}),
        "execution_callbacks_wired": callback_wired(callback_rows, {"execDetails", "commissionReport"}),
        "market_data_callbacks_wired": callback_wired(callback_rows, {"tickPrice", "tickSize", "tickString", "tickGeneric"}),
        "quote_fields_fresh": quote_execution_ready,
        "ask_fresh": ask_fresh,
        "bid_fresh": bid_fresh,
        "last_fresh": last_fresh,
        "quote_execution_ready": quote_execution_ready,
        "blocked_reason": blocked_reason,
        "market_session_state": market.get("session_state"),
        "expected_live_bid_ask": market.get("expected_live_bid_ask"),
        "callback_wiring": callback_rows,
        "bus_state_sources": bus_state_sources(bus),
        "last_event_source_categories": ["REAL_IBKR", "SIMULATION", "TEST_FIXTURE", "LOCAL_SCRIPT", "NONE"],
        "latest_bus_state_version": bus.get("state_version"),
        "latest_sync_snapshot_id": sync.get("snapshot_id"),
        "latest_streaming_diagnostics_path": "reports/streaming_quote_diagnostics/latest.json" if streaming else "",
        "stale_ask_explanation": {
            "meaning": "stale_ask means the ask price is old/not fresh, not sale.",
            "does_not_mean_callback_failure": True,
            "blocks_real_paper_buy_execution": True,
            "blocks_local_simulation": False,
            "market_closed_note": "During closed/after-hours sessions, bid/ask can be stale or unavailable while callback registration is still healthy.",
        },
    }
    write_report(report)
    update_realtime_reports(report)
    return report


def callback_row(callback_name: str, bus: dict[str, Any], dry_run: dict[str, Any]) -> dict[str, Any]:
    modules = SOURCE_MODULES.get(callback_name, [])
    registered = any(callback_defined(callback_name, PROJECT_ROOT / module) for module in modules)
    wired_modules = [module for module in modules if callback_wires_bus(callback_name, PROJECT_ROOT / module)]
    wired = bool(wired_modules)
    callback_count = int((dry_run.get("callback_counts") or {}).get(callback_name) or 0)
    last_seen = str((dry_run.get("last_event_seen_at") or {}).get(callback_name) or "")
    state_version = bus.get("state_version") if wired else None
    return {
        "callback_name": callback_name,
        "callback_registered": registered,
        "can_receive_real_ibkr_callback": registered,
        "wired_to_realtime_bus": wired,
        "source_module": ", ".join(wired_modules or modules),
        "event_type_written": EVENT_TYPES.get(callback_name, ""),
        "last_event_seen_at": last_seen,
        "last_event_source": "REAL_IBKR" if callback_count > 0 else "NONE",
        "real_ibkr_event_count": callback_count,
        "latest_state_version": state_version,
        "report_path": "reports/ibkr_callback_wiring/latest.json",
        "notes": callback_notes(callback_name, registered, wired),
    }


def bus_state_sources(bus: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for key in [
        "latest_account_state",
        "latest_position_state",
        "latest_quote_state",
        "latest_pnl_state",
        "latest_open_order_state",
        "latest_execution_state",
        "latest_risk_state",
    ]:
        state = bus.get(key) if isinstance(bus.get(key), dict) else {}
        source_module = str(state.get("source_module") or "")
        if source_module == "bootstrap_simulation":
            source = "SIMULATION"
        elif source_module.startswith("test"):
            source = "TEST_FIXTURE"
        elif source_module:
            source = "LOCAL_SCRIPT"
        else:
            source = "NONE"
        rows.append(
            {
                "state_key": key,
                "source_module": source_module,
                "last_event_source": source,
                "state_version": state.get("state_version"),
                "timestamp_utc": state.get("timestamp_utc"),
            }
        )
    return rows


def callback_defined(callback_name: str, path: Path) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    return f"def {callback_name}(" in text or f"def {callback_name}(  " in text


def callback_wires_bus(callback_name: str, path: Path) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    marker = f"def {callback_name}"
    index = text.find(marker)
    if index < 0:
        return False
    next_def = text.find("\n    def ", index + len(marker))
    body = text[index: next_def if next_def > index else len(text)]
    return "RealtimeAccountStateBus" in body or "_record_callback(" in body or ".update(" in body and "realtime" in body.lower()


def latest_bus_timestamp_for_callback(callback_name: str, bus: dict[str, Any]) -> str:
    state_key = {
        "tickPrice": "latest_quote_state",
        "tickSize": "latest_quote_state",
        "tickString": "latest_quote_state",
        "tickGeneric": "latest_quote_state",
        "updateAccountValue": "latest_account_state",
        "updatePortfolio": "latest_position_state",
        "position": "latest_position_state",
        "pnl": "latest_pnl_state",
        "pnlSingle": "latest_pnl_state",
        "openOrder": "latest_open_order_state",
        "orderStatus": "latest_open_order_state",
        "execDetails": "latest_execution_state",
        "commissionReport": "latest_execution_state",
        "error": "latest_risk_state",
    }.get(callback_name, "")
    state = bus.get(state_key) if state_key else {}
    return str((state or {}).get("timestamp_utc") or "")


def callback_notes(callback_name: str, registered: bool, wired: bool) -> str:
    if wired:
        return "callback directly updates RealtimeAccountStateBus"
    if registered:
        return "callback exists in an IBKR wrapper/client, but it currently updates local report/client state rather than RealtimeAccountStateBus"
    return "callback not found in current local IBKR wrapper code"


def callback_wired(rows: list[dict[str, Any]], names: set[str]) -> bool:
    return any(row["callback_name"] in names and row["wired_to_realtime_bus"] for row in rows)


def tws_socket_available() -> bool:
    try:
        settings = Settings.load()
        with socket.create_connection((settings.tws_host, settings.tws_port), timeout=0.25):
            return True
    except Exception:
        return False


def update_realtime_reports(wiring_report: dict[str, Any]) -> None:
    for name in ["realtime_account_state_bus", "realtime_account_sync"]:
        path = PROJECT_ROOT / "reports" / name / "latest.json"
        payload = read_json(path)
        if not payload:
            continue
        payload["ibkr_callback_wiring_audit"] = {
            "report_path": "reports/ibkr_callback_wiring/latest.json",
            "bus_ok": wiring_report["bus_ok"],
            "callbacks_registered": wiring_report["callbacks_registered"],
            "market_data_callbacks_wired": wiring_report["market_data_callbacks_wired"],
            "account_callbacks_wired": wiring_report["account_callbacks_wired"],
            "position_callbacks_wired": wiring_report["position_callbacks_wired"],
            "pnl_callbacks_wired": wiring_report["pnl_callbacks_wired"],
            "order_callbacks_wired": wiring_report["order_callbacks_wired"],
            "execution_callbacks_wired": wiring_report["execution_callbacks_wired"],
            "quote_execution_ready": wiring_report["quote_execution_ready"],
            "blocked_reason": wiring_report["blocked_reason"],
            "stale_ask_explanation": wiring_report["stale_ask_explanation"],
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        md_path = path.with_suffix(".md")
        existing = md_path.read_text(encoding="utf-8") if md_path.exists() else f"# {name}\n"
        addition = "\n## IBKR Callback Wiring Audit\n\n" + "\n".join(
            [
                f"- bus_ok: {wiring_report['bus_ok']}",
                f"- callbacks_registered: {wiring_report['callbacks_registered']}",
                f"- market_data_callbacks_wired: {wiring_report['market_data_callbacks_wired']}",
                f"- quote_execution_ready: {wiring_report['quote_execution_ready']}",
                f"- blocked_reason: {wiring_report['blocked_reason']}",
                "- stale_ask means old/not fresh ask, not sale.",
            ]
        ) + "\n"
        md_path.write_text(existing + addition, encoding="utf-8")


def write_report(report: dict[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "latest.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    lines = [
        "# IBKR Callback Wiring Audit",
        "",
        f"- bus_running: {report['bus_running']}",
        f"- bus_ok: {report['bus_ok']}",
        f"- ibkr_connected: {report['ibkr_connected']}",
        f"- callbacks_registered: {report['callbacks_registered']}",
        f"- market_data_callbacks_wired: {report['market_data_callbacks_wired']}",
        f"- quote_execution_ready: {report['quote_execution_ready']}",
        f"- blocked_reason: {report['blocked_reason']}",
        "",
        "stale_ask means the ask price is old/not fresh, not sale. It blocks real BUY execution readiness, but does not block local simulation and does not prove callback wiring failed.",
        "",
        "| Callback | Registered | Wired To Bus | Source | Last Source | Notes |",
        "|---|---:|---:|---|---|---|",
    ]
    for row in report["callback_wiring"]:
        lines.append(
            f"| {row['callback_name']} | {row['callback_registered']} | {row['wired_to_realtime_bus']} | "
            f"{row['source_module']} | {row['last_event_source']} | {row['notes']} |"
        )
    (REPORT_DIR / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
