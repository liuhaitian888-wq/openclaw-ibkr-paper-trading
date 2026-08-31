import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from trading.config import PROJECT_ROOT, Settings


@dataclass(frozen=True)
class PaperEnvironmentAuditItem:
    name: str
    status: str
    required: bool
    detail: str


@dataclass(frozen=True)
class PaperEnvironmentAuditReport:
    source: str
    created_at: str
    status: str
    api_url: str
    api_reachable: bool
    api_error: str
    local_settings: dict[str, Any]
    health: Optional[dict[str, Any]]
    items: list[PaperEnvironmentAuditItem] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)


def build_environment_audit(
    settings: Settings,
    *,
    health: Optional[Mapping[str, Any]] = None,
    api_url: str = "http://127.0.0.1:8787",
    api_error: str = "",
) -> PaperEnvironmentAuditReport:
    health_dict = None if health is None else dict(health)
    api_reachable = health_dict is not None and not api_error
    items = _audit_items(settings, health_dict, api_reachable=api_reachable, api_error=api_error)
    status = _report_status(items, health_dict)
    return PaperEnvironmentAuditReport(
        source="paper_environment_audit",
        created_at=datetime.now(timezone.utc).isoformat(),
        status=status,
        api_url=api_url,
        api_reachable=api_reachable,
        api_error=api_error,
        local_settings=_settings_snapshot(settings),
        health=health_dict,
        items=items,
        next_steps=_next_steps(status, items),
    )


def write_environment_audit(report: PaperEnvironmentAuditReport, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(asdict(report), indent=2, sort_keys=True), encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit local Trading API, TWS, and safety settings before a one-share paper trial. This never places orders."
    )
    parser.add_argument("--api-url", default="http://127.0.0.1:8787")
    parser.add_argument("--api-key-file", type=Path, default=PROJECT_ROOT / ".secrets" / "openclaw_api_key")
    parser.add_argument("--api-timeout", type=float, default=5.0)
    parser.add_argument("--health-json", type=Path)
    parser.add_argument("--no-api-health", action="store_true")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "reports" / "paper_environment_audit.json")
    args = parser.parse_args()

    settings = Settings.load()
    health = None
    api_error = ""
    if args.health_json is not None:
        health = _load_json_object(args.health_json)
    elif not args.no_api_health:
        api_key = ""
        if args.api_key_file.exists():
            api_key = args.api_key_file.read_text(encoding="utf-8").strip()
        health, api_error = fetch_health(args.api_url, api_key=api_key, timeout=args.api_timeout)

    report = build_environment_audit(settings, health=health, api_url=args.api_url, api_error=api_error)
    write_environment_audit(report, args.output)
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    return 0


def fetch_health(api_url: str, *, api_key: str, timeout: float) -> tuple[Optional[dict[str, Any]], str]:
    if not api_key:
        return None, "API key file is missing or empty"
    request = urllib.request.Request(
        api_url.rstrip("/") + "/health",
        method="GET",
        headers={"X-API-Key": api_key},
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return None, f"Trading API returned HTTP {exc.code}"
    except Exception as exc:
        return None, str(exc)
    if not isinstance(payload, dict):
        return None, "Trading API /health did not return a JSON object"
    payload["audit_round_trip_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return payload, ""


def _audit_items(
    settings: Settings,
    health: Optional[Mapping[str, Any]],
    *,
    api_reachable: bool,
    api_error: str,
) -> list[PaperEnvironmentAuditItem]:
    items = [
        _item(
            "api_key_present",
            bool(settings.api_key),
            True,
            "local API key is configured" if settings.api_key else "local API key is missing",
        ),
        _item(
            "live_trading_unavailable",
            settings.trading_mode in {"DRY_RUN", "PAPER"},
            True,
            f"configured mode is {settings.trading_mode}; no live mode is accepted by Settings",
        ),
        _item(
            "paper_mode",
            settings.trading_mode == "PAPER",
            True,
            f"TRADING_MODE={settings.trading_mode}",
        ),
        _item(
            "kill_switch_off",
            not settings.trading_kill_switch,
            True,
            f"TRADING_KILL_SWITCH={settings.trading_kill_switch}",
        ),
        _item(
            "paper_transmit_enabled",
            settings.allow_paper_transmit,
            True,
            f"ALLOW_PAPER_TRANSMIT={settings.allow_paper_transmit}",
        ),
        _item(
            "trade_session_token_present",
            bool(settings.trade_session_token),
            True,
            "trade session token is configured" if settings.trade_session_token else "trade session token is missing",
        ),
        _item(
            "one_share_limit",
            settings.max_quantity <= 1,
            True,
            f"MAX_QUANTITY={settings.max_quantity}",
        ),
        _item(
            "small_order_value_limit",
            settings.max_order_value <= 500.0,
            True,
            f"MAX_ORDER_VALUE={settings.max_order_value}",
        ),
        _item(
            "allowed_symbols_present",
            len(settings.allowed_symbols) > 0,
            True,
            f"{len(settings.allowed_symbols)} allowed symbols configured",
        ),
        _item(
            "paper_tws_port",
            settings.tws_port == 7497,
            False,
            f"TWS_PORT={settings.tws_port}; 7497 is the standard paper TWS port",
        ),
        _item(
            "api_health_reachable",
            api_reachable,
            True,
            "Trading API /health responded" if api_reachable else f"Trading API /health unavailable: {api_error or 'not checked'}",
        ),
    ]
    items.extend(_health_items(health))
    return items


def _health_items(health: Optional[Mapping[str, Any]]) -> list[PaperEnvironmentAuditItem]:
    if health is None:
        return [
            PaperEnvironmentAuditItem(
                "health_lock_state",
                "unknown",
                True,
                "Trading API /health was not available",
            ),
            PaperEnvironmentAuditItem(
                "health_tws_ready",
                "unknown",
                True,
                "Trading API /health was not available",
            ),
        ]
    tws = health.get("tws", {})
    if not isinstance(tws, Mapping):
        tws = {}
    paper_account = tws.get("paper_account")
    return [
        _item(
            "health_lock_state",
            health.get("lock_state") == "TRADE_LOCK",
            True,
            f"lock_state={health.get('lock_state')}",
        ),
        _item(
            "health_paper_transmit_enabled",
            health.get("paper_transmit_enabled") is True,
            True,
            f"paper_transmit_enabled={health.get('paper_transmit_enabled')}",
        ),
        _item(
            "health_kill_switch_off",
            health.get("kill_switch_enabled") is False,
            True,
            f"kill_switch_enabled={health.get('kill_switch_enabled')}",
        ),
        _item(
            "health_tws_ready",
            tws.get("ready_for_orders") is True,
            True,
            f"ready_for_orders={tws.get('ready_for_orders')}; error={tws.get('error', '')}",
        ),
        _item(
            "health_du_paper_account",
            isinstance(paper_account, str) and paper_account.startswith("DU"),
            True,
            f"paper_account={paper_account}",
        ),
    ]


def _item(name: str, condition: bool, required: bool, detail: str) -> PaperEnvironmentAuditItem:
    return PaperEnvironmentAuditItem(
        name=name,
        status="pass" if condition else "fail",
        required=required,
        detail=detail,
    )


def _report_status(items: list[PaperEnvironmentAuditItem], health: Optional[Mapping[str, Any]]) -> str:
    required_failures = [item for item in items if item.required and item.status == "fail"]
    required_unknowns = [item for item in items if item.required and item.status == "unknown"]
    if not required_failures and not required_unknowns:
        return "ready_for_one_share_paper_trial"
    if health is None and not required_failures:
        return "api_or_tws_check_required"
    return "blocked"


def _next_steps(status: str, items: list[PaperEnvironmentAuditItem]) -> list[str]:
    if status == "ready_for_one_share_paper_trial":
        return [
            "Run the full paper trial pipeline with --submit-validate.",
            "Review paper_validation_plan.json and paper_readiness_report.json.",
            "Only then use --execute-paper with PAPER_ONLY_1_SHARE for a single paper limit order.",
        ]
    steps = []
    failures = [item for item in items if item.required and item.status in {"fail", "unknown"}]
    for item in failures:
        if item.name == "api_health_reachable":
            steps.append("Start the Trading API in TRADE_LOCK or provide a saved --health-json file.")
        elif item.name == "paper_mode":
            steps.append("Start the API with TRADING_MODE=PAPER for any TWS paper action.")
        elif item.name == "kill_switch_off":
            steps.append("Disable the kill switch only for an intentional paper-trading window.")
        elif item.name == "paper_transmit_enabled":
            steps.append("Set ALLOW_PAPER_TRANSMIT=true only when ready for paper transmission.")
        elif item.name == "trade_session_token_present":
            steps.append("Generate and configure a fresh trade session token.")
        elif item.name == "health_tws_ready":
            steps.append("Log into TWS paper or IB Gateway paper and enable API access on localhost.")
        elif item.name == "health_du_paper_account":
            steps.append("Confirm the connected IBKR session exposes exactly one DU paper account.")
        elif item.name == "health_lock_state":
            steps.append("Use TRADE_LOCK for paper submission; DEV_LOCK is fine for validation-only work.")
    if not steps:
        steps.append("Inspect failed audit items and keep order size at one share.")
    return _dedupe(steps)


def _settings_snapshot(settings: Settings) -> dict[str, Any]:
    return {
        "api_host": settings.api_host,
        "api_port": settings.api_port,
        "trading_mode": settings.trading_mode,
        "allow_tws_staging": settings.allow_tws_staging,
        "allow_paper_transmit": settings.allow_paper_transmit,
        "allow_outside_rth": settings.allow_outside_rth,
        "trading_kill_switch": settings.trading_kill_switch,
        "trade_session_token_present": bool(settings.trade_session_token),
        "tws_host": settings.tws_host,
        "tws_port": settings.tws_port,
        "tws_client_id": settings.tws_client_id,
        "tws_status_timeout": settings.tws_status_timeout,
        "allowed_symbol_count": len(settings.allowed_symbols),
        "max_quantity": settings.max_quantity,
        "max_order_value": settings.max_order_value,
        "max_risk_per_order": settings.max_risk_per_order,
        "audit_db": str(settings.audit_db),
    }


def _load_json_object(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
