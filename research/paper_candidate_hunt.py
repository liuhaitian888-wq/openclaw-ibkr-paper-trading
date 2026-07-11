import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.guarded_paper_trial_session import GuardedPaperTrialSessionConfig, GuardedPaperTrialSessionReport, run_guarded_session
from research.ibkr_quote_recorder import QuoteSource
from research.quote_quality_report import build_quote_quality_report, write_quote_quality_json, write_quote_quality_markdown
from trading.config import Settings
from trading.paper_environment_audit import fetch_health


@dataclass(frozen=True)
class CandidateHuntAttempt:
    attempt: int
    created_at: str
    guarded_status: str
    pipeline_status: str
    quote_quality_status: str
    quote_rows_written: int
    validate_payload_count: int
    gate_status: str


@dataclass(frozen=True)
class PaperCandidateHuntReport:
    source: str
    created_at: str
    status: str
    attempts: list[CandidateHuntAttempt] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PaperCandidateHuntConfig:
    symbols: Sequence[str]
    max_attempts: int = 3
    pause_seconds: float = 30.0
    samples: int = 30
    interval_seconds: float = 5.0
    market_data_type: int = 3
    api_url: str = "http://127.0.0.1:8787"
    api_key: str = ""
    api_timeout: float = 20.0
    output_report: Path = PROJECT_ROOT / "reports" / "paper_candidate_hunt.json"
    quotes_csv: Path = PROJECT_ROOT / "data" / "ibkr_quotes.csv"
    quote_quality_json: Path = PROJECT_ROOT / "reports" / "quote_quality_report.json"
    quote_quality_md: Path = PROJECT_ROOT / "reports" / "quote_quality_report.md"
    recorder_report: Path = PROJECT_ROOT / "reports" / "ibkr_quote_recorder.json"
    diagnostics_report: Path = PROJECT_ROOT / "reports" / "mean_reversion_diagnostics.json"
    paper_plan_report: Path = PROJECT_ROOT / "reports" / "paper_validation_plan.json"
    ibkr_pipeline_report: Path = PROJECT_ROOT / "reports" / "ibkr_mean_reversion_pipeline.json"
    readiness_report: Path = PROJECT_ROOT / "reports" / "paper_readiness_report.json"
    execution_gate_report: Path = PROJECT_ROOT / "reports" / "paper_execution_gate.json"
    full_pipeline_report: Path = PROJECT_ROOT / "reports" / "full_paper_trial_pipeline.json"
    environment_audit_report: Path = PROJECT_ROOT / "reports" / "paper_environment_audit.json"
    guarded_session_report: Path = PROJECT_ROOT / "reports" / "guarded_paper_trial_session.json"


QuoteSourceFactory = Callable[[int], QuoteSource]
HealthProvider = Callable[[], tuple[Optional[Mapping[str, Any]], str]]


def run_candidate_hunt(
    settings: Settings,
    config: PaperCandidateHuntConfig,
    *,
    quote_source_factory: QuoteSourceFactory,
    health_provider: HealthProvider,
) -> PaperCandidateHuntReport:
    attempts: list[CandidateHuntAttempt] = []
    max_attempts = max(1, config.max_attempts)
    for attempt in range(1, max_attempts + 1):
        health, api_error = health_provider()
        guarded = run_guarded_session(
            quote_source_factory(attempt),
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
                submit_validate=True,
                execute_paper=False,
            ),
        )
        quote_quality = build_quote_quality_report(config.quotes_csv) if config.quotes_csv.exists() else None
        if quote_quality is not None:
            write_quote_quality_json(quote_quality, config.quote_quality_json)
            write_quote_quality_markdown(quote_quality, config.quote_quality_md)

        full_pipeline = _load_optional_json(config.full_pipeline_report)
        gate = _load_optional_json(config.execution_gate_report)
        hunt_attempt = CandidateHuntAttempt(
            attempt=attempt,
            created_at=datetime.now(timezone.utc).isoformat(),
            guarded_status=guarded.status,
            pipeline_status=str((full_pipeline or {}).get("status", guarded.pipeline_status or "missing")),
            quote_quality_status="missing" if quote_quality is None else quote_quality.status,
            quote_rows_written=_int_value(full_pipeline, "quote_rows_written"),
            validate_payload_count=_int_value(full_pipeline, "validate_payload_count"),
            gate_status=str((gate or {}).get("status", "missing")),
        )
        attempts.append(hunt_attempt)
        if _candidate_found(hunt_attempt):
            break
        if attempt < max_attempts and config.pause_seconds > 0:
            time.sleep(config.pause_seconds)

    report = PaperCandidateHuntReport(
        source="paper_candidate_hunt",
        created_at=datetime.now(timezone.utc).isoformat(),
        status=_hunt_status(attempts[-1]),
        attempts=attempts,
        artifacts={
            "output_report": str(config.output_report),
            "quotes_csv": str(config.quotes_csv),
            "quote_quality_json": str(config.quote_quality_json),
            "quote_quality_md": str(config.quote_quality_md),
            "guarded_session": str(config.guarded_session_report),
            "full_pipeline": str(config.full_pipeline_report),
            "paper_plan": str(config.paper_plan_report),
            "execution_gate": str(config.execution_gate_report),
        },
    )
    config.output_report.parent.mkdir(parents=True, exist_ok=True)
    config.output_report.write_text(json.dumps(asdict(report), indent=2, sort_keys=True), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Hunt for a real IBKR validate payload without paper order submission.")
    parser.add_argument("--symbols", default="AAPL,MSFT,SPY")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--pause-seconds", type=float, default=30.0)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--interval-seconds", type=float, default=5.0)
    parser.add_argument("--market-data-type", type=int, default=3)
    parser.add_argument("--api-url", default="http://127.0.0.1:8787")
    parser.add_argument("--api-key-file", type=Path, default=PROJECT_ROOT / ".secrets" / "openclaw_api_key")
    parser.add_argument("--api-timeout", type=float, default=20.0)
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--client-id", type=int, default=470)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--exchange", default="SMART")
    parser.add_argument("--primary-exchange", default="")
    args = parser.parse_args()

    from trading.ibkr_readonly import IbkrReadOnlyQuoteSource

    settings = Settings.load()
    api_key = args.api_key_file.read_text(encoding="utf-8").strip() if args.api_key_file.exists() else ""

    def health_provider() -> tuple[Optional[Mapping[str, Any]], str]:
        return fetch_health(args.api_url, api_key=api_key, timeout=args.api_timeout)

    def source_factory(attempt: int) -> QuoteSource:
        return IbkrReadOnlyQuoteSource(
            host=args.host or settings.tws_host,
            port=args.port or settings.tws_port,
            client_id=args.client_id + attempt - 1,
            timeout=args.timeout,
            snapshot=True,
            market_data_type=args.market_data_type,
            exchange=args.exchange,
            primary_exchange=args.primary_exchange,
        )

    report = run_candidate_hunt(
        settings,
        PaperCandidateHuntConfig(
            symbols=[symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()],
            max_attempts=args.max_attempts,
            pause_seconds=args.pause_seconds,
            samples=args.samples,
            interval_seconds=args.interval_seconds,
            market_data_type=args.market_data_type,
            api_url=args.api_url,
            api_key=api_key,
            api_timeout=args.api_timeout,
        ),
        quote_source_factory=source_factory,
        health_provider=health_provider,
    )
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    return 0


def _candidate_found(attempt: CandidateHuntAttempt) -> bool:
    return attempt.validate_payload_count > 0 or attempt.gate_status == "ready_for_explicit_paper_submit"


def _hunt_status(attempt: CandidateHuntAttempt) -> str:
    if _candidate_found(attempt):
        return "validate_payload_found"
    if attempt.guarded_status == "environment_blocked":
        return "environment_blocked"
    if attempt.quote_quality_status == "static_last_prices":
        return "no_candidate_static_quotes"
    return "no_candidate_found"


def _int_value(payload: Optional[Mapping[str, Any]], key: str) -> int:
    if payload is None:
        return 0
    try:
        return int(payload.get(key, 0))
    except (TypeError, ValueError):
        return 0


def _load_optional_json(path: Path) -> Optional[Mapping[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
