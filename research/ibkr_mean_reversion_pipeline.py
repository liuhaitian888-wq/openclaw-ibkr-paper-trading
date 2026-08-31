import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.ibkr_quote_recorder import QuoteRecorderConfig, QuoteRecorderReport, QuoteSource, record_quotes
from research.mean_reversion_diagnostics import PriceDiagnostics, diagnose_symbol_prices, read_prices_csv, write_report
from research.paper_validation_plan import (
    PaperValidationPlan,
    build_plan,
    submit_validate_payloads,
    write_plan,
)
from trading.config import Settings


@dataclass(frozen=True)
class IbkrMeanReversionPipelineConfig:
    symbols: Sequence[str]
    samples: int = 30
    interval_seconds: float = 60.0
    quotes_csv: Path = Path("data/ibkr_quotes.csv")
    recorder_report: Path = Path("reports/ibkr_quote_recorder.json")
    diagnostics_report: Path = Path("reports/mean_reversion_diagnostics.json")
    paper_plan_report: Path = Path("reports/paper_validation_plan.json")
    pipeline_report: Path = Path("reports/ibkr_mean_reversion_pipeline.json")
    z_window: int = 20
    entry_z: float = 1.0
    quantity: int = 1
    submit_validate: bool = False
    api_url: str = "http://127.0.0.1:8787"
    api_key: str = ""
    api_timeout: float = 15.0


@dataclass(frozen=True)
class IbkrMeanReversionPipelineReport:
    source: str
    created_at: str
    requested_symbols: List[str]
    quotes_csv: str
    recorder_report: str
    diagnostics_report: str
    paper_plan_report: str
    quote_rows_written: int
    diagnostic_count: int
    verdict_counts: dict[str, int]
    paper_plan_candidate_count: int
    paper_plan_validate_payload_count: int
    paper_plan_submitted_validate: bool
    recorder_errors: List[str]


def run_pipeline(source: QuoteSource, config: IbkrMeanReversionPipelineConfig) -> IbkrMeanReversionPipelineReport:
    symbols = [symbol.strip().upper() for symbol in config.symbols if symbol.strip()]
    if not symbols:
        raise ValueError("symbols must not be empty")

    recorder = record_quotes(
        source,
        QuoteRecorderConfig(
            symbols=symbols,
            samples=config.samples,
            interval_seconds=config.interval_seconds,
            output_csv=config.quotes_csv,
            output_report=config.recorder_report,
        ),
    )
    diagnostics = _diagnose_csv(config.quotes_csv, z_window=config.z_window)
    write_report(diagnostics, config.diagnostics_report)
    paper_plan = _paper_plan(diagnostics, config)
    write_plan(paper_plan, config.paper_plan_report)
    report = _pipeline_report(symbols, recorder, diagnostics, paper_plan, config)
    config.pipeline_report.parent.mkdir(parents=True, exist_ok=True)
    config.pipeline_report.write_text(json.dumps(asdict(report), indent=2, sort_keys=True), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Record read-only IBKR quotes and immediately run mean-reversion diagnostics. This script does not place orders."
    )
    parser.add_argument("--symbols", default="AAPL,MSFT,SPY")
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--interval-seconds", type=float, default=60.0)
    parser.add_argument("--quotes-csv", type=Path, default=PROJECT_ROOT / "data" / "ibkr_quotes.csv")
    parser.add_argument("--recorder-report", type=Path, default=PROJECT_ROOT / "reports" / "ibkr_quote_recorder.json")
    parser.add_argument("--diagnostics-report", type=Path, default=PROJECT_ROOT / "reports" / "mean_reversion_diagnostics.json")
    parser.add_argument("--paper-plan-report", type=Path, default=PROJECT_ROOT / "reports" / "paper_validation_plan.json")
    parser.add_argument("--pipeline-report", type=Path, default=PROJECT_ROOT / "reports" / "ibkr_mean_reversion_pipeline.json")
    parser.add_argument("--z-window", type=int, default=20)
    parser.add_argument("--entry-z", type=float, default=1.0)
    parser.add_argument("--quantity", type=int, default=1)
    parser.add_argument("--submit-validate", action="store_true")
    parser.add_argument("--api-url", default="http://127.0.0.1:8787")
    parser.add_argument("--api-key-file", type=Path, default=PROJECT_ROOT / ".secrets" / "openclaw_api_key")
    parser.add_argument("--api-timeout", type=float, default=15.0)
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--client-id", type=int, default=430)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--exchange", default="SMART")
    parser.add_argument("--primary-exchange", default="")
    parser.add_argument("--market-data-type", type=int, default=3)
    args = parser.parse_args()

    from trading.ibkr_readonly import IbkrReadOnlyQuoteSource

    settings = Settings.load()
    api_key = ""
    if args.submit_validate:
        api_key = args.api_key_file.read_text(encoding="utf-8").strip()
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
    report = run_pipeline(
        source,
        IbkrMeanReversionPipelineConfig(
            symbols=[symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()],
            samples=args.samples,
            interval_seconds=args.interval_seconds,
            quotes_csv=args.quotes_csv,
            recorder_report=args.recorder_report,
            diagnostics_report=args.diagnostics_report,
            paper_plan_report=args.paper_plan_report,
            pipeline_report=args.pipeline_report,
            z_window=args.z_window,
            entry_z=args.entry_z,
            quantity=args.quantity,
            submit_validate=args.submit_validate,
            api_url=args.api_url,
            api_key=api_key,
            api_timeout=args.api_timeout,
        ),
    )
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    return 0


def _diagnose_csv(path: Path, *, z_window: int) -> List[PriceDiagnostics]:
    symbol_prices = read_prices_csv(path, price_column="close", symbol_column="symbol")
    return [
        diagnose_symbol_prices(symbol, prices, z_window=z_window)
        for symbol, prices in sorted(symbol_prices.items())
    ]


def _paper_plan(
    diagnostics: Sequence[PriceDiagnostics],
    config: IbkrMeanReversionPipelineConfig,
) -> PaperValidationPlan:
    plan = build_plan(
        [asdict(item) for item in diagnostics],
        diagnostics_path=config.diagnostics_report,
        entry_z=config.entry_z,
        quantity=config.quantity,
    )
    if config.submit_validate:
        if not config.api_key:
            raise ValueError("api_key is required when submit_validate is true")
        plan = submit_validate_payloads(
            plan,
            api_url=config.api_url,
            api_key=config.api_key,
            timeout=config.api_timeout,
        )
    return plan


def _pipeline_report(
    symbols: List[str],
    recorder: QuoteRecorderReport,
    diagnostics: Sequence[PriceDiagnostics],
    paper_plan: PaperValidationPlan,
    config: IbkrMeanReversionPipelineConfig,
) -> IbkrMeanReversionPipelineReport:
    verdict_counts: dict[str, int] = {}
    for item in diagnostics:
        verdict = item.diagnostics.verdict
        verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
    return IbkrMeanReversionPipelineReport(
        source="ibkr_mean_reversion_pipeline",
        created_at=datetime.now(timezone.utc).isoformat(),
        requested_symbols=symbols,
        quotes_csv=str(config.quotes_csv),
        recorder_report=str(config.recorder_report),
        diagnostics_report=str(config.diagnostics_report),
        paper_plan_report=str(config.paper_plan_report),
        quote_rows_written=recorder.quote_rows_written,
        diagnostic_count=len(diagnostics),
        verdict_counts=verdict_counts,
        paper_plan_candidate_count=paper_plan.candidate_count,
        paper_plan_validate_payload_count=paper_plan.validate_payload_count,
        paper_plan_submitted_validate=config.submit_validate,
        recorder_errors=recorder.errors,
    )


if __name__ == "__main__":
    raise SystemExit(main())
