import argparse
import csv
import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Protocol, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.config import Settings
from trading.market_data import Quote


class QuoteSource(Protocol):
    last_errors: List[str]

    def get_quotes(self, symbols: Sequence[str]) -> List[Quote]:
        raise NotImplementedError


@dataclass(frozen=True)
class QuoteRecorderConfig:
    symbols: Sequence[str]
    samples: int = 30
    interval_seconds: float = 60.0
    output_csv: Path = Path("data/ibkr_quotes.csv")
    output_report: Path = Path("reports/ibkr_quote_recorder.json")


@dataclass(frozen=True)
class QuoteRecorderReport:
    source: str
    created_at: str
    requested_symbols: List[str]
    samples_requested: int
    samples_completed: int
    quote_rows_written: int
    output_csv: str
    errors: List[str]


def record_quotes(source: QuoteSource, config: QuoteRecorderConfig) -> QuoteRecorderReport:
    symbols = [symbol.strip().upper() for symbol in config.symbols if symbol.strip()]
    if not symbols:
        raise ValueError("symbols must not be empty")
    if config.samples <= 0:
        raise ValueError("samples must be positive")
    if config.interval_seconds < 0:
        raise ValueError("interval_seconds must not be negative")

    config.output_csv.parent.mkdir(parents=True, exist_ok=True)
    config.output_report.parent.mkdir(parents=True, exist_ok=True)
    rows_written = 0
    all_errors: List[str] = []
    with config.output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "sample",
                "requested_at",
                "symbol",
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "last",
                "bid",
                "ask",
                "spread",
                "volume",
                "quote_source",
            ],
        )
        writer.writeheader()
        for sample in range(config.samples):
            requested_at = datetime.now(timezone.utc).isoformat()
            quotes = source.get_quotes(symbols)
            all_errors.extend(_new_errors(all_errors, getattr(source, "last_errors", [])))
            for quote in quotes:
                writer.writerow(_quote_row(sample, requested_at, quote))
                rows_written += 1
            if sample < config.samples - 1 and config.interval_seconds > 0:
                time.sleep(config.interval_seconds)

    report = QuoteRecorderReport(
        source="ibkr_quote_recorder",
        created_at=datetime.now(timezone.utc).isoformat(),
        requested_symbols=symbols,
        samples_requested=config.samples,
        samples_completed=config.samples,
        quote_rows_written=rows_written,
        output_csv=str(config.output_csv),
        errors=all_errors,
    )
    config.output_report.write_text(json.dumps(asdict(report), indent=2, sort_keys=True), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Record read-only IBKR quotes to a research CSV. This script does not place orders."
    )
    parser.add_argument("--symbols", default="AAPL,MSFT,SPY")
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--interval-seconds", type=float, default=60.0)
    parser.add_argument("--output-csv", type=Path, default=PROJECT_ROOT / "data" / "ibkr_quotes.csv")
    parser.add_argument("--output-report", type=Path, default=PROJECT_ROOT / "reports" / "ibkr_quote_recorder.json")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--client-id", type=int, default=410)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--exchange", default="SMART")
    parser.add_argument("--primary-exchange", default="")
    parser.add_argument(
        "--market-data-type",
        type=int,
        default=3,
        help="IBKR market data type: 1 real-time, 3 delayed, 4 delayed-frozen.",
    )
    args = parser.parse_args()

    from trading.ibkr_readonly import IbkrReadOnlyQuoteSource

    settings = Settings.load()
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
    report = record_quotes(
        source,
        QuoteRecorderConfig(
            symbols=[symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()],
            samples=args.samples,
            interval_seconds=args.interval_seconds,
            output_csv=args.output_csv,
            output_report=args.output_report,
        ),
    )
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    return 0


def _quote_row(sample: int, requested_at: str, quote: Quote) -> dict[str, object]:
    spread = quote.spread
    return {
        "sample": sample,
        "requested_at": requested_at,
        "symbol": quote.symbol.upper(),
        "timestamp": quote.timestamp.isoformat(),
        "open": quote.last,
        "high": quote.last,
        "low": quote.last,
        "close": quote.last,
        "last": quote.last,
        "bid": "" if quote.bid is None else quote.bid,
        "ask": "" if quote.ask is None else quote.ask,
        "spread": "" if spread is None else spread,
        "volume": "" if quote.volume is None else quote.volume,
        "quote_source": quote.source,
    }


def _new_errors(existing: Iterable[str], errors: Iterable[str]) -> List[str]:
    seen = set(existing)
    return [error for error in errors if error and error not in seen]


if __name__ == "__main__":
    raise SystemExit(main())
