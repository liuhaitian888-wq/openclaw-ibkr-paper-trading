import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.ibkr_mean_reversion_pipeline import IbkrMeanReversionPipelineConfig, run_pipeline
from research.ibkr_quote_recorder import QuoteSource
from research.paper_execution_gate import build_gate_report, execute_if_confirmed, write_report as write_gate_report
from research.paper_readiness_report import build_readiness_report, load_plan, write_readiness_report
from trading.config import Settings


@dataclass(frozen=True)
class FullPaperTrialPipelineConfig:
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


@dataclass(frozen=True)
class FullPaperTrialPipelineReport:
    source: str
    created_at: str
    requested_symbols: List[str]
    status: str
    quote_rows_written: int
    diagnostic_count: int
    validate_payload_count: int
    submitted_validate: bool
    readiness_status: str
    gate_status: str
    gate_mode: str
    paper_submitted: bool
    artifacts: dict[str, str]


def run_full_pipeline(source: QuoteSource, config: FullPaperTrialPipelineConfig) -> FullPaperTrialPipelineReport:
    symbols = [symbol.strip().upper() for symbol in config.symbols if symbol.strip()]
    if not symbols:
        raise ValueError("symbols must not be empty")

    ibkr_report = run_pipeline(
        source,
        IbkrMeanReversionPipelineConfig(
            symbols=symbols,
            samples=config.samples,
            interval_seconds=config.interval_seconds,
            quotes_csv=config.quotes_csv,
            recorder_report=config.recorder_report,
            diagnostics_report=config.diagnostics_report,
            paper_plan_report=config.paper_plan_report,
            pipeline_report=config.ibkr_pipeline_report,
            z_window=config.z_window,
            entry_z=config.entry_z,
            quantity=config.quantity,
            submit_validate=config.submit_validate,
            api_url=config.api_url,
            api_key=config.api_key,
            api_timeout=config.api_timeout,
        ),
    )
    plan = load_plan(config.paper_plan_report)
    readiness = build_readiness_report(plan, plan_path=config.paper_plan_report)
    write_readiness_report(readiness, config.readiness_report)

    gate = build_gate_report(
        asdict(readiness),
        plan,
        readiness_path=config.readiness_report,
        plan_path=config.paper_plan_report,
    )
    if config.execute_paper:
        gate = execute_if_confirmed(
            gate,
            confirm=config.confirm,
            trade_session_token=config.trade_session_token,
            api_url=config.api_url,
            api_key=config.api_key,
            timeout=config.api_timeout,
        )
    write_gate_report(gate, config.execution_gate_report)

    report = FullPaperTrialPipelineReport(
        source="full_paper_trial_pipeline",
        created_at=datetime.now(timezone.utc).isoformat(),
        requested_symbols=symbols,
        status=_overall_status(readiness.status, gate.status),
        quote_rows_written=ibkr_report.quote_rows_written,
        diagnostic_count=ibkr_report.diagnostic_count,
        validate_payload_count=ibkr_report.paper_plan_validate_payload_count,
        submitted_validate=config.submit_validate,
        readiness_status=readiness.status,
        gate_status=gate.status,
        gate_mode=gate.mode,
        paper_submitted=gate.status == "submitted",
        artifacts=_artifacts(config),
    )
    config.full_pipeline_report.parent.mkdir(parents=True, exist_ok=True)
    config.full_pipeline_report.write_text(json.dumps(asdict(report), indent=2, sort_keys=True), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the read-only IBKR quote, diagnostics, validate-plan, readiness, and paper-gate pipeline. "
            "Dry-run by default."
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
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--client-id", type=int, default=440)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--exchange", default="SMART")
    parser.add_argument("--primary-exchange", default="")
    parser.add_argument("--market-data-type", type=int, default=3)
    args = parser.parse_args()

    from trading.ibkr_readonly import IbkrReadOnlyQuoteSource

    settings = Settings.load()
    api_key = ""
    if args.submit_validate or args.execute_paper:
        api_key = args.api_key_file.read_text(encoding="utf-8").strip()
    token = ""
    if args.trade_session_token_file is not None and args.trade_session_token_file.exists():
        token = args.trade_session_token_file.read_text(encoding="utf-8").strip()
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
    report = run_full_pipeline(
        source,
        FullPaperTrialPipelineConfig(
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
        ),
    )
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    return 0


def _overall_status(readiness_status: str, gate_status: str) -> str:
    if gate_status == "submitted":
        return "paper_submitted"
    if gate_status == "ready_for_explicit_paper_submit":
        return "ready_for_explicit_paper_submit"
    if readiness_status == "validate_required":
        return "validate_required"
    return "not_ready_for_paper"


def _artifacts(config: FullPaperTrialPipelineConfig) -> dict[str, str]:
    return {
        "quotes_csv": str(config.quotes_csv),
        "recorder_report": str(config.recorder_report),
        "diagnostics_report": str(config.diagnostics_report),
        "paper_plan_report": str(config.paper_plan_report),
        "ibkr_pipeline_report": str(config.ibkr_pipeline_report),
        "readiness_report": str(config.readiness_report),
        "execution_gate_report": str(config.execution_gate_report),
        "full_pipeline_report": str(config.full_pipeline_report),
    }


if __name__ == "__main__":
    raise SystemExit(main())
