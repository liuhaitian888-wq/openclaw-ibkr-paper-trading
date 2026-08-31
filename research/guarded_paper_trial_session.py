import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Mapping, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.full_paper_trial_pipeline import FullPaperTrialPipelineConfig, FullPaperTrialPipelineReport, run_full_pipeline
from research.ibkr_quote_recorder import QuoteSource
from trading.config import Settings
from trading.paper_environment_audit import (
    PaperEnvironmentAuditReport,
    build_environment_audit,
    fetch_health,
    write_environment_audit,
)


READY_STATUS = "ready_for_one_share_paper_trial"


@dataclass(frozen=True)
class GuardedPaperTrialSessionConfig:
    symbols: Sequence[str]
    samples: int = 30
    interval_seconds: float = 60.0
    quotes_csv: Path = Path("data/ibkr_quotes.csv")
    recorder_report: Path = Path("reports/ibkr_quote_recorder.json")
    diagnostics_report: Path = Path("reports/mean_reversion_diagnostics.json")
    paper_plan_report: Path = Path("reports/paper_validation_plan.json")
    ibkr_pipeline_report: Path = Path("reports/ibkr_mean_reversion_pipeline.json")
    readiness_report: Path = Path("reports/paper_readiness_report.json")
    execution_gate_report: Path = Path("reports/paper_execution_gate.json")
    full_pipeline_report: Path = Path("reports/full_paper_trial_pipeline.json")
    environment_audit_report: Path = Path("reports/paper_environment_audit.json")
    guarded_session_report: Path = Path("reports/guarded_paper_trial_session.json")
    z_window: int = 20
    entry_z: float = 1.0
    quantity: int = 1
    submit_validate: bool = False
    execute_paper: bool = False
    confirm: str = ""
    trade_session_token: str = ""
    api_url: str = "http://127.0.0.1:8787"
    api_key: str = ""
    api_timeout: float = 20.0
    require_environment_ready: bool = True


@dataclass(frozen=True)
class GuardedPaperTrialSessionReport:
    source: str
    created_at: str
    requested_symbols: List[str]
    status: str
    reason: str
    environment_status: str
    pipeline_status: Optional[str]
    paper_submitted: bool
    artifacts: dict[str, str]


def run_guarded_session(
    source: QuoteSource,
    settings: Settings,
    *,
    health: Optional[Mapping[str, Any]],
    api_error: str,
    config: GuardedPaperTrialSessionConfig,
) -> GuardedPaperTrialSessionReport:
    symbols = [symbol.strip().upper() for symbol in config.symbols if symbol.strip()]
    if not symbols:
        raise ValueError("symbols must not be empty")

    environment = build_environment_audit(
        settings,
        health=health,
        api_url=config.api_url,
        api_error=api_error,
    )
    write_environment_audit(environment, config.environment_audit_report)

    if config.require_environment_ready and environment.status != READY_STATUS:
        report = _session_report(
            symbols,
            config,
            environment,
            pipeline=None,
            status="environment_blocked",
            reason=f"environment audit status is {environment.status}",
        )
        _write_session_report(report, config.guarded_session_report)
        return report

    pipeline = run_full_pipeline(
        source,
        FullPaperTrialPipelineConfig(
            symbols=symbols,
            samples=config.samples,
            interval_seconds=config.interval_seconds,
            quotes_csv=config.quotes_csv,
            recorder_report=config.recorder_report,
            diagnostics_report=config.diagnostics_report,
            paper_plan_report=config.paper_plan_report,
            ibkr_pipeline_report=config.ibkr_pipeline_report,
            readiness_report=config.readiness_report,
            execution_gate_report=config.execution_gate_report,
            full_pipeline_report=config.full_pipeline_report,
            z_window=config.z_window,
            entry_z=config.entry_z,
            quantity=config.quantity,
            submit_validate=config.submit_validate,
            execute_paper=config.execute_paper,
            confirm=config.confirm,
            trade_session_token=config.trade_session_token,
            api_url=config.api_url,
            api_key=config.api_key,
            api_timeout=config.api_timeout,
        ),
    )
    report = _session_report(
        symbols,
        config,
        environment,
        pipeline=pipeline,
        status=_session_status(pipeline),
        reason="full paper trial pipeline completed",
    )
    _write_session_report(report, config.guarded_session_report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run a guarded one-share paper-trial session: environment audit first, "
            "then read-only IBKR data, diagnostics, validation, readiness, and paper gate."
        )
    )
    parser.add_argument("--symbols", default="AAPL,MSFT,SPY")
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--interval-seconds", type=float, default=60.0)
    parser.add_argument("--quotes-csv", type=Path, default=PROJECT_ROOT / "data" / "ibkr_quotes.csv")
    parser.add_argument("--recorder-report", type=Path, default=PROJECT_ROOT / "reports" / "ibkr_quote_recorder.json")
    parser.add_argument("--diagnostics-report", type=Path, default=PROJECT_ROOT / "reports" / "mean_reversion_diagnostics.json")
    parser.add_argument("--paper-plan-report", type=Path, default=PROJECT_ROOT / "reports" / "paper_validation_plan.json")
    parser.add_argument("--ibkr-pipeline-report", type=Path, default=PROJECT_ROOT / "reports" / "ibkr_mean_reversion_pipeline.json")
    parser.add_argument("--readiness-report", type=Path, default=PROJECT_ROOT / "reports" / "paper_readiness_report.json")
    parser.add_argument("--execution-gate-report", type=Path, default=PROJECT_ROOT / "reports" / "paper_execution_gate.json")
    parser.add_argument("--full-pipeline-report", type=Path, default=PROJECT_ROOT / "reports" / "full_paper_trial_pipeline.json")
    parser.add_argument("--environment-audit-report", type=Path, default=PROJECT_ROOT / "reports" / "paper_environment_audit.json")
    parser.add_argument("--guarded-session-report", type=Path, default=PROJECT_ROOT / "reports" / "guarded_paper_trial_session.json")
    parser.add_argument("--z-window", type=int, default=20)
    parser.add_argument("--entry-z", type=float, default=1.0)
    parser.add_argument("--quantity", type=int, default=1)
    parser.add_argument("--submit-validate", action="store_true")
    parser.add_argument("--execute-paper", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--trade-session-token-file", type=Path)
    parser.add_argument("--api-url", default="http://127.0.0.1:8787")
    parser.add_argument("--api-key-file", type=Path, default=PROJECT_ROOT / ".secrets" / "openclaw_api_key")
    parser.add_argument("--api-timeout", type=float, default=20.0)
    parser.add_argument("--health-json", type=Path)
    parser.add_argument("--allow-unready-environment", action="store_true")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--client-id", type=int, default=450)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--exchange", default="SMART")
    parser.add_argument("--primary-exchange", default="")
    parser.add_argument("--market-data-type", type=int, default=3)
    args = parser.parse_args()

    from trading.ibkr_readonly import IbkrReadOnlyQuoteSource

    settings = Settings.load()
    api_key = args.api_key_file.read_text(encoding="utf-8").strip() if args.api_key_file.exists() else ""
    token = ""
    if args.trade_session_token_file is not None and args.trade_session_token_file.exists():
        token = args.trade_session_token_file.read_text(encoding="utf-8").strip()
    health, api_error = _load_or_fetch_health(args.health_json, args.api_url, api_key, args.api_timeout)
    source = IbkrReadOnlyQuoteSource(
        host=args.host or settings.tws_host,
        port=args.port or settings.tws_port,
        client_id=args.client_id,
        timeout=args.timeout,
        snapshot=True,
        market_data_type=args.market_data_type,
        exchange=args.exchange,
        primary_exchange=args.primary_exchange,
    )
    report = run_guarded_session(
        source,
        settings,
        health=health,
        api_error=api_error,
        config=GuardedPaperTrialSessionConfig(
            symbols=[symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()],
            samples=args.samples,
            interval_seconds=args.interval_seconds,
            quotes_csv=args.quotes_csv,
            recorder_report=args.recorder_report,
            diagnostics_report=args.diagnostics_report,
            paper_plan_report=args.paper_plan_report,
            ibkr_pipeline_report=args.ibkr_pipeline_report,
            readiness_report=args.readiness_report,
            execution_gate_report=args.execution_gate_report,
            full_pipeline_report=args.full_pipeline_report,
            environment_audit_report=args.environment_audit_report,
            guarded_session_report=args.guarded_session_report,
            z_window=args.z_window,
            entry_z=args.entry_z,
            quantity=args.quantity,
            submit_validate=args.submit_validate,
            execute_paper=args.execute_paper,
            confirm=args.confirm,
            trade_session_token=token,
            api_url=args.api_url,
            api_key=api_key,
            api_timeout=args.api_timeout,
            require_environment_ready=not args.allow_unready_environment,
        ),
    )
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    return 0 if report.status != "environment_blocked" else 2


def _load_or_fetch_health(
    health_json: Optional[Path],
    api_url: str,
    api_key: str,
    timeout: float,
) -> tuple[Optional[dict[str, Any]], str]:
    if health_json is not None:
        payload = json.loads(health_json.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"{health_json} must contain a JSON object")
        return payload, ""
    return fetch_health(api_url, api_key=api_key, timeout=timeout)


def _session_report(
    symbols: List[str],
    config: GuardedPaperTrialSessionConfig,
    environment: PaperEnvironmentAuditReport,
    *,
    pipeline: Optional[FullPaperTrialPipelineReport],
    status: str,
    reason: str,
) -> GuardedPaperTrialSessionReport:
    return GuardedPaperTrialSessionReport(
        source="guarded_paper_trial_session",
        created_at=datetime.now(timezone.utc).isoformat(),
        requested_symbols=symbols,
        status=status,
        reason=reason,
        environment_status=environment.status,
        pipeline_status=None if pipeline is None else pipeline.status,
        paper_submitted=False if pipeline is None else pipeline.paper_submitted,
        artifacts=_artifacts(config),
    )


def _session_status(pipeline: FullPaperTrialPipelineReport) -> str:
    if pipeline.paper_submitted:
        return "paper_submitted"
    if pipeline.status == "ready_for_explicit_paper_submit":
        return "ready_for_explicit_paper_submit"
    if pipeline.status == "validate_required":
        return "validate_required"
    return "completed_without_paper_candidate"


def _artifacts(config: GuardedPaperTrialSessionConfig) -> dict[str, str]:
    return {
        "environment_audit_report": str(config.environment_audit_report),
        "quotes_csv": str(config.quotes_csv),
        "recorder_report": str(config.recorder_report),
        "diagnostics_report": str(config.diagnostics_report),
        "paper_plan_report": str(config.paper_plan_report),
        "ibkr_pipeline_report": str(config.ibkr_pipeline_report),
        "readiness_report": str(config.readiness_report),
        "execution_gate_report": str(config.execution_gate_report),
        "full_pipeline_report": str(config.full_pipeline_report),
        "guarded_session_report": str(config.guarded_session_report),
    }


def _write_session_report(report: GuardedPaperTrialSessionReport, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(asdict(report), indent=2, sort_keys=True), encoding="utf-8")
    return output


if __name__ == "__main__":
    raise SystemExit(main())
