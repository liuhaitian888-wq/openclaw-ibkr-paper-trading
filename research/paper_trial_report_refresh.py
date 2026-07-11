import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.guarded_paper_trial_session import GuardedPaperTrialSessionConfig, run_guarded_session
from research.ibkr_quote_recorder import QuoteSource
from research.paper_session_runbook import build_runbook, write_runbook_json, write_runbook_markdown
from research.paper_session_status_page import write_status_page
from research.paper_trial_evidence_bundle import build_evidence_bundle, write_evidence_bundle, write_evidence_markdown
from research.paper_trial_preflight_checklist import (
    build_preflight_checklist,
    write_preflight_json,
    write_preflight_markdown,
)
from research.paper_trial_reconciliation import build_reconciliation, write_reconciliation
from research.project_completion_audit import (
    build_completion_audit,
    write_completion_audit_json,
    write_completion_audit_markdown,
)
from trading.audit import AuditLog
from trading.config import Settings
from trading.paper_environment_audit import build_environment_audit, fetch_health, write_environment_audit


@dataclass(frozen=True)
class PaperTrialReportRefreshConfig:
    symbols: Sequence[str]
    samples: int = 30
    interval_seconds: float = 60.0
    market_data_type: int = 3
    api_url: str = "http://127.0.0.1:8787"
    api_key: str = ""
    api_timeout: float = 20.0
    quotes_csv: Path = PROJECT_ROOT / "data" / "ibkr_quotes.csv"
    recorder_report: Path = PROJECT_ROOT / "reports" / "ibkr_quote_recorder.json"
    diagnostics_report: Path = PROJECT_ROOT / "reports" / "mean_reversion_diagnostics.json"
    paper_plan_report: Path = PROJECT_ROOT / "reports" / "paper_validation_plan.json"
    ibkr_pipeline_report: Path = PROJECT_ROOT / "reports" / "ibkr_mean_reversion_pipeline.json"
    readiness_report: Path = PROJECT_ROOT / "reports" / "paper_readiness_report.json"
    execution_gate_report: Path = PROJECT_ROOT / "reports" / "paper_execution_gate.json"
    full_pipeline_report: Path = PROJECT_ROOT / "reports" / "full_paper_trial_pipeline.json"
    environment_audit_report: Path = PROJECT_ROOT / "reports" / "paper_environment_audit.json"
    guarded_session_report: Path = PROJECT_ROOT / "reports" / "guarded_paper_trial_session.json"
    reconciliation_report: Path = PROJECT_ROOT / "reports" / "paper_trial_reconciliation.json"
    tws_orders_json: Path = PROJECT_ROOT / "reports" / "tws_orders_snapshot.json"
    pnl_jsonl: Path = PROJECT_ROOT / "reports" / "pnl_timeseries.jsonl"
    runbook_json: Path = PROJECT_ROOT / "reports" / "paper_session_runbook.json"
    runbook_md: Path = PROJECT_ROOT / "reports" / "paper_session_runbook.md"
    status_html: Path = PROJECT_ROOT / "reports" / "paper_session_status.html"
    evidence_json: Path = PROJECT_ROOT / "reports" / "paper_trial_evidence_bundle.json"
    evidence_md: Path = PROJECT_ROOT / "reports" / "paper_trial_evidence_bundle.md"
    rehearsal_report: Path = PROJECT_ROOT / "reports" / "paper_trial_rehearsal" / "paper_trial_rehearsal.json"
    preflight_json: Path = PROJECT_ROOT / "reports" / "paper_trial_preflight_checklist.json"
    preflight_md: Path = PROJECT_ROOT / "reports" / "paper_trial_preflight_checklist.md"
    strategy_catalog_json: Path = PROJECT_ROOT / "reports" / "strategy_catalog.json"
    readiness_monitor_json: Path = PROJECT_ROOT / "reports" / "paper_trial_readiness_monitor.json"
    completion_audit_json: Path = PROJECT_ROOT / "reports" / "project_completion_audit.json"
    completion_audit_md: Path = PROJECT_ROOT / "reports" / "project_completion_audit.md"
    quote_quality_json: Path = PROJECT_ROOT / "reports" / "quote_quality_report.json"


@dataclass(frozen=True)
class PaperTrialReportRefreshReport:
    source: str
    created_at: str
    status: str
    environment_status: str
    guarded_session_status: str
    reconciliation_status: str
    evidence_stage: str
    artifacts: dict[str, str]


QuoteSourceFactory = Callable[[], QuoteSource]


def refresh_reports(
    settings: Settings,
    config: PaperTrialReportRefreshConfig,
    *,
    health: Optional[Mapping[str, Any]],
    api_error: str,
    quote_source_factory: QuoteSourceFactory,
) -> PaperTrialReportRefreshReport:
    environment = build_environment_audit(settings, health=health, api_url=config.api_url, api_error=api_error)
    write_environment_audit(environment, config.environment_audit_report)

    source: QuoteSource = _BlockedQuoteSource()
    if environment.status == "ready_for_one_share_paper_trial":
        source = quote_source_factory()
    guarded = run_guarded_session(
        source,
        settings,
        health=health,
        api_error=api_error,
        config=GuardedPaperTrialSessionConfig(
            symbols=config.symbols,
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
            environment_audit_report=config.environment_audit_report,
            guarded_session_report=config.guarded_session_report,
            api_url=config.api_url,
            api_key=config.api_key,
            api_timeout=config.api_timeout,
            require_environment_ready=True,
        ),
    )

    execution_gate = _load_optional_json(config.execution_gate_report)
    reconciliation = build_reconciliation(
        execution_gate,
        audit_order=_load_audit_order(settings.audit_db, _idempotency_from_gate(execution_gate)),
        tws_orders=_load_optional_json(config.tws_orders_json),
        pnl_sample=_load_latest_jsonl(config.pnl_jsonl),
        artifacts={
            "execution_gate": str(config.execution_gate_report),
            "tws_orders_json": str(config.tws_orders_json),
            "pnl_jsonl": str(config.pnl_jsonl),
            "audit_db": str(settings.audit_db),
            "output": str(config.reconciliation_report),
        },
    )
    write_reconciliation(reconciliation, config.reconciliation_report)

    runbook = build_runbook(
        asdict(environment),
        asdict(guarded),
        symbols=",".join(config.symbols),
        samples=config.samples,
        interval_seconds=config.interval_seconds,
        market_data_type=config.market_data_type,
    )
    write_runbook_json(runbook, config.runbook_json)
    write_runbook_markdown(runbook, config.runbook_md)
    write_status_page(asdict(runbook), config.status_html)

    preflight = build_preflight_checklist(
        asdict(environment),
        asdict(runbook),
        rehearsal=_load_optional_json(config.rehearsal_report),
    )
    write_preflight_json(preflight, config.preflight_json)
    write_preflight_markdown(preflight, config.preflight_md)

    evidence = build_evidence_bundle(
        audit=asdict(environment),
        guarded_session=asdict(guarded),
        runbook=asdict(runbook),
        reconciliation=asdict(reconciliation),
        artifact_paths={
            "environment_audit": config.environment_audit_report,
            "guarded_session": config.guarded_session_report,
            "runbook_json": config.runbook_json,
            "reconciliation": config.reconciliation_report,
            "status_html": config.status_html,
            "preflight_json": config.preflight_json,
            "quote_quality_json": config.quote_quality_json,
        },
    )
    write_evidence_bundle(evidence, config.evidence_json)
    write_evidence_markdown(evidence, config.evidence_md)

    completion_audit = build_completion_audit(
        strategy_catalog=_load_optional_json(config.strategy_catalog_json),
        preflight=asdict(preflight),
        evidence_bundle=asdict(evidence),
        readiness_monitor=_load_optional_json(config.readiness_monitor_json),
        rehearsal=_load_optional_json(config.rehearsal_report),
        full_pipeline=_load_optional_json(config.full_pipeline_report),
        quote_quality=_load_optional_json(config.quote_quality_json),
    )
    write_completion_audit_json(completion_audit, config.completion_audit_json)
    write_completion_audit_markdown(completion_audit, config.completion_audit_md)

    return PaperTrialReportRefreshReport(
        source="paper_trial_report_refresh",
        created_at=datetime.now(timezone.utc).isoformat(),
        status="refreshed_blocked" if evidence.stage == "blocked_before_paper_window" else "refreshed",
        environment_status=environment.status,
        guarded_session_status=guarded.status,
        reconciliation_status=reconciliation.status,
        evidence_stage=evidence.stage,
        artifacts=_artifacts(config),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh the complete paper-trial report set in safe order.")
    parser.add_argument("--symbols", default="AAPL,MSFT,SPY")
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--interval-seconds", type=float, default=60.0)
    parser.add_argument("--market-data-type", type=int, default=3)
    parser.add_argument("--api-url", default="http://127.0.0.1:8787")
    parser.add_argument("--api-key-file", type=Path, default=PROJECT_ROOT / ".secrets" / "openclaw_api_key")
    parser.add_argument("--api-timeout", type=float, default=20.0)
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--client-id", type=int, default=460)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--exchange", default="SMART")
    parser.add_argument("--primary-exchange", default="")
    args = parser.parse_args()

    settings = Settings.load()
    api_key = args.api_key_file.read_text(encoding="utf-8").strip() if args.api_key_file.exists() else ""
    health, api_error = fetch_health(args.api_url, api_key=api_key, timeout=args.api_timeout)

    def factory() -> QuoteSource:
        from trading.ibkr_readonly import IbkrReadOnlyQuoteSource

        return IbkrReadOnlyQuoteSource(
            host=args.host or settings.tws_host,
            port=args.port or settings.tws_port,
            client_id=args.client_id,
            timeout=args.timeout,
            snapshot=True,
            market_data_type=args.market_data_type,
            exchange=args.exchange,
            primary_exchange=args.primary_exchange,
        )

    report = refresh_reports(
        settings,
        PaperTrialReportRefreshConfig(
            symbols=[symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()],
            samples=args.samples,
            interval_seconds=args.interval_seconds,
            market_data_type=args.market_data_type,
            api_url=args.api_url,
            api_key=api_key,
            api_timeout=args.api_timeout,
        ),
        health=health,
        api_error=api_error,
        quote_source_factory=factory,
    )
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    return 0


class _BlockedQuoteSource:
    last_errors: list[str] = []

    def get_quotes(self, symbols: Sequence[str]) -> list[Any]:
        raise RuntimeError("quote source should not be used when environment is blocked")


def _artifacts(config: PaperTrialReportRefreshConfig) -> dict[str, str]:
    return {
        "environment_audit": str(config.environment_audit_report),
        "guarded_session": str(config.guarded_session_report),
        "reconciliation": str(config.reconciliation_report),
        "runbook_json": str(config.runbook_json),
        "runbook_md": str(config.runbook_md),
        "status_html": str(config.status_html),
        "evidence_json": str(config.evidence_json),
        "evidence_md": str(config.evidence_md),
        "preflight_json": str(config.preflight_json),
        "preflight_md": str(config.preflight_md),
        "completion_audit_json": str(config.completion_audit_json),
        "completion_audit_md": str(config.completion_audit_md),
    }


def _load_optional_json(path: Path) -> Optional[Mapping[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _load_latest_jsonl(path: Path) -> Optional[Mapping[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return None
    latest = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            latest = line
    if not latest:
        return None
    payload = json.loads(latest)
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain JSON objects")
    return payload


def _idempotency_from_gate(execution_gate: Optional[Mapping[str, Any]]) -> Optional[str]:
    if execution_gate is None:
        return None
    payload = execution_gate.get("selected_payload")
    if not isinstance(payload, Mapping):
        return None
    value = payload.get("idempotency_key")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _load_audit_order(audit_db: Path, idempotency_key: Optional[str]) -> Optional[Mapping[str, Any]]:
    if not idempotency_key or not audit_db.exists():
        return None
    order = AuditLog(audit_db).get(idempotency_key)
    if order is None:
        return None
    return {"status": "ok", "order": order}


if __name__ == "__main__":
    raise SystemExit(main())
