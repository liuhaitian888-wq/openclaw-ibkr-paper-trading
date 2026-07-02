"""Fetch read-only IBKR quotes and print the normalized cache snapshot.

This command does not place orders. It is for checking what the current IBKR
market-data permissions return for symbols such as AAPL, MSFT, and QQQ.
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.config import Settings
from trading.ibkr_readonly import IbkrReadOnlyQuoteSource
from trading.market_data import InMemoryQuoteCache


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="AAPL,MSFT,QQQ")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--client-id", type=int, default=31)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument(
        "--exchange",
        default="SMART",
        help="IBKR contract exchange, for example SMART or IEX.",
    )
    parser.add_argument(
        "--market-data-type",
        type=int,
        default=1,
        help="IBKR market data type: 1 real-time, 3 delayed, 4 delayed-frozen.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = Settings.load()
    source = IbkrReadOnlyQuoteSource(
        host=args.host or settings.tws_host,
        port=args.port or settings.tws_port,
        client_id=args.client_id,
        timeout=args.timeout,
        snapshot=True,
        market_data_type=args.market_data_type,
        exchange=args.exchange,
    )
    symbols = [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()]
    cache = InMemoryQuoteCache()
    quotes = source.get_quotes(symbols)
    cache.update_many(quotes)
    payload = {
        "source": "ibkr_readonly",
        "requested_symbols": symbols,
        "quote_count": len(quotes),
        "exchange": args.exchange,
        "errors": source.last_errors,
        "quotes": [
            {
                "symbol": quote.symbol,
                "last": quote.last,
                "bid": quote.bid,
                "ask": quote.ask,
                "close": quote.close,
                "volume": quote.volume,
                "age_ms": quote.age_ms(),
                "spread": quote.spread,
                "source": quote.source,
                "timestamp": quote.timestamp.isoformat(),
            }
            for quote in cache.snapshot().values()
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
