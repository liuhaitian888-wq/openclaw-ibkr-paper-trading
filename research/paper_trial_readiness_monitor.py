import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.paper_session_runbook import build_runbook, write_runbook_json, write_runbook_markdown
from research.paper_trial_preflight_checklist import (
    build_preflight_checklist,
    write_preflight_json,
    write_preflight_markdown,
)
from trading.config import Settings
from trading.paper_environment_audit import build_environment_audit, fetch_health, write_environment_audit


@dataclass(frozen=True)
class ReadinessMonitorSnapshot:
    attempt: int
    created_at: str
    api_error: str
    environment_status: str
    runbook_status: str
    preflight_status: str
    next_allowed_action: str


@dataclass(frozen=True)
class PaperTrialReadinessMonitorReport:
    source: str
    created_at: str
    status: str
    attempts: int
    snapshots: list[ReadinessMonitorSnapshot] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)


HealthProvider = Callable[[], tuple[Optional[Mapping[str, Any]], str]]


@dataclass(frozen=True)
class PaperTrialReadinessMonitorConfig:
    max_attempts: int = 1
    interval_seconds: float = 5.0
    api_url: str = "http://127.0.0.1:8787"
    symbols: str = "AAPL,MSFT,SPY"
    samples: int = 30
    interval_for_runbook: float = 60.0
    market_data_type: int = 3
    environment_audit_report: Path = PROJECT_ROOT / "reports" / "paper_environment_audit.json"
    runbook_json: Path = PROJECT_ROOT / "reports" / "paper_session_runbook.json"
    runbook_md: Path = PROJECT_ROOT / "reports" / "paper_session_runbook.md"
    rehearsal_report: Path = PROJECT_ROOT / "reports" / "paper_trial_rehearsal" / "paper_trial_rehearsal.json"
    preflight_json: Path = PROJECT_ROOT / "reports" / "paper_trial_preflight_checklist.json"
    preflight_md: Path = PROJECT_ROOT / "reports" / "paper_trial_preflight_checklist.md"
    monitor_json: Path = PROJECT_ROOT / "reports" / "paper_trial_readiness_monitor.json"


def run_readiness_monitor(
    settings: Settings,
    config: PaperTrialReadinessMonitorConfig,
    *,
    health_provider: HealthProvider,
) -> PaperTrialReadinessMonitorReport:
    snapshots: list[ReadinessMonitorSnapshot] = []
    attempts = max(1, config.max_attempts)
    for attempt in range(1, attempts + 1):
        health, api_error = health_provider()
        environment = build_environment_audit(settings, health=health, api_url=config.api_url, api_error=api_error)
        write_environment_audit(environment, config.environment_audit_report)

        runbook = build_runbook(
            asdict(environment),
            None,
            symbols=config.symbols,
            samples=config.samples,
            interval_seconds=config.interval_for_runbook,
            market_data_type=config.market_data_type,
        )
        write_runbook_json(runbook, config.runbook_json)
        write_runbook_markdown(runbook, config.runbook_md)

        preflight = build_preflight_checklist(
            asdict(environment),
            asdict(runbook),
            rehearsal=_load_optional_json_object(config.rehearsal_report),
        )
        write_preflight_json(preflight, config.preflight_json)
        write_preflight_markdown(preflight, config.preflight_md)

        snapshot = ReadinessMonitorSnapshot(
            attempt=attempt,
            created_at=datetime.now(timezone.utc).isoformat(),
            api_error=api_error,
            environment_status=environment.status,
            runbook_status=runbook.status,
            preflight_status=preflight.status,
            next_allowed_action=preflight.next_allowed_action,
        )
        snapshots.append(snapshot)
        if preflight.status == "ready_for_validate_only_window":
            break
        if attempt < attempts:
            time.sleep(config.interval_seconds)

    report = PaperTrialReadinessMonitorReport(
        source="paper_trial_readiness_monitor",
        created_at=datetime.now(timezone.utc).isoformat(),
        status=_monitor_status(snapshots[-1]),
        attempts=len(snapshots),
        snapshots=snapshots,
        artifacts={
            "environment_audit": str(config.environment_audit_report),
            "runbook_json": str(config.runbook_json),
            "runbook_md": str(config.runbook_md),
            "preflight_json": str(config.preflight_json),
            "preflight_md": str(config.preflight_md),
            "monitor_json": str(config.monitor_json),
        },
    )
    config.monitor_json.parent.mkdir(parents=True, exist_ok=True)
    config.monitor_json.write_text(json.dumps(asdict(report), indent=2, sort_keys=True), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Safely poll Trading API/TWS readiness and update preflight artifacts without quotes, validation, or orders."
    )
    parser.add_argument("--api-url", default="http://127.0.0.1:8787")
    parser.add_argument("--api-key-file", type=Path, default=PROJECT_ROOT / ".secrets" / "openclaw_api_key")
    parser.add_argument("--api-timeout", type=float, default=5.0)
    parser.add_argument("--max-attempts", type=int, default=1)
    parser.add_argument("--interval-seconds", type=float, default=5.0)
    parser.add_argument("--symbols", default="AAPL,MSFT,SPY")
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--runbook-interval-seconds", type=float, default=60.0)
    parser.add_argument("--market-data-type", type=int, default=3)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "reports" / "paper_trial_readiness_monitor.json")
    args = parser.parse_args()

    settings = Settings.load()
    api_key = args.api_key_file.read_text(encoding="utf-8").strip() if args.api_key_file.exists() else ""

    def provider() -> tuple[Optional[Mapping[str, Any]], str]:
        return fetch_health(args.api_url, api_key=api_key, timeout=args.api_timeout)

    report = run_readiness_monitor(
        settings,
        PaperTrialReadinessMonitorConfig(
            max_attempts=args.max_attempts,
            interval_seconds=args.interval_seconds,
            api_url=args.api_url,
            symbols=args.symbols,
            samples=args.samples,
            interval_for_runbook=args.runbook_interval_seconds,
            market_data_type=args.market_data_type,
            monitor_json=args.output,
        ),
        health_provider=provider,
    )
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    return 0


def _monitor_status(snapshot: ReadinessMonitorSnapshot) -> str:
    if snapshot.preflight_status == "ready_for_validate_only_window":
        return "ready_for_validate_only_window"
    return "waiting_for_real_ibkr_window"


def _load_optional_json_object(path: Path) -> Optional[Mapping[str, Any]]:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
