"""Benchmark read-only IBKR quote request latency by batch size.

This command only requests market data. It does not place orders.
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.config import Settings
from trading.ibkr_readonly import IbkrReadOnlyQuoteSource


DEFAULT_SYMBOLS = "AAPL,MSFT,NVDA,TSLA,AMD,INTC,NFLX"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    parser.add_argument(
        "--batch-sizes",
        default="1,2,4,7",
        help="Comma-separated batch sizes to test against the leading symbols.",
    )
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--pause-seconds", type=float, default=1.0)
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--client-id-base", type=int, default=700)
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--exchange", default="SMART")
    parser.add_argument(
        "--market-data-type",
        type=int,
        default=3,
        help="IBKR market data type: 1 real-time, 3 delayed, 4 delayed-frozen.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = Settings.load()
    symbols = parse_symbols(args.symbols)
    batch_sizes = parse_batch_sizes(args.batch_sizes, len(symbols))

    runs: List[Dict[str, object]] = []
    client_id = args.client_id_base
    for batch_size in batch_sizes:
        batch_symbols = symbols[:batch_size]
        for repeat in range(args.repeats):
            client_id += 1
            source = IbkrReadOnlyQuoteSource(
                host=args.host or settings.tws_host,
                port=args.port or settings.tws_port,
                client_id=client_id,
                timeout=args.timeout,
                snapshot=True,
                market_data_type=args.market_data_type,
                exchange=args.exchange,
            )
            started = time.perf_counter()
            quotes = source.get_quotes(batch_symbols)
            elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
            returned = sorted(quote.symbol for quote in quotes)
            runs.append(
                {
                    "batch_size": batch_size,
                    "repeat": repeat + 1,
                    "client_id": client_id,
                    "requested_symbols": batch_symbols,
                    "returned_symbols": returned,
                    "missing_symbols": [
                        symbol for symbol in batch_symbols if symbol not in returned
                    ],
                    "quote_count": len(quotes),
                    "elapsed_ms": elapsed_ms,
                    "quote_ages_ms": {
                        quote.symbol: quote.age_ms()
                        for quote in sorted(quotes, key=lambda item: item.symbol)
                    },
                    "errors": source.last_errors,
                }
            )
            if args.pause_seconds > 0:
                time.sleep(args.pause_seconds)

    payload = {
        "source": "ibkr_quote_batch_benchmark",
        "symbols": symbols,
        "exchange": args.exchange,
        "market_data_type": args.market_data_type,
        "timeout_seconds": args.timeout,
        "repeats": args.repeats,
        "runs": runs,
        "summary": summarize(runs),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def parse_symbols(raw_symbols: str) -> List[str]:
    return [symbol.strip().upper() for symbol in raw_symbols.split(",") if symbol.strip()]


def parse_batch_sizes(raw_batch_sizes: str, max_size: int) -> List[int]:
    sizes = []
    for raw_size in raw_batch_sizes.split(","):
        raw_size = raw_size.strip()
        if not raw_size:
            continue
        size = int(raw_size)
        if size <= 0:
            raise ValueError("batch sizes must be positive")
        sizes.append(min(size, max_size))
    return sorted(set(sizes))


def summarize(runs: List[Dict[str, object]]) -> List[Dict[str, object]]:
    grouped: Dict[int, List[Dict[str, object]]] = {}
    for run in runs:
        grouped.setdefault(int(run["batch_size"]), []).append(run)

    summary = []
    for batch_size, batch_runs in sorted(grouped.items()):
        elapsed_values = [float(run["elapsed_ms"]) for run in batch_runs]
        quote_counts = [int(run["quote_count"]) for run in batch_runs]
        summary.append(
            {
                "batch_size": batch_size,
                "runs": len(batch_runs),
                "avg_elapsed_ms": round(statistics.mean(elapsed_values), 3),
                "min_elapsed_ms": round(min(elapsed_values), 3),
                "max_elapsed_ms": round(max(elapsed_values), 3),
                "avg_quote_count": round(statistics.mean(quote_counts), 3),
                "full_success_runs": sum(
                    1 for run in batch_runs if int(run["quote_count"]) == batch_size
                ),
            }
        )
    return summary


if __name__ == "__main__":
    raise SystemExit(main())
