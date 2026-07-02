"""Diagnose read-only IBKR market data channels in order.

The script only requests market data. It does not place orders.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.config import Settings
from trading.ibkr_readonly import IbkrReadOnlyQuoteSource
from trading.market_data import InMemoryQuoteCache


CHANNELS = [
    ("smart_delayed", "SMART", 3),
    ("smart_realtime", "SMART", 1),
    ("iex_realtime", "IEX", 1),
    ("smart_delayed_frozen", "SMART", 4),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="AAPL,MSFT,QQQ")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--client-id-base", type=int, default=80)
    parser.add_argument("--timeout", type=float, default=8.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = Settings.load()
    symbols = [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()]

    checks: List[Dict[str, object]] = []
    for index, (name, exchange, market_data_type) in enumerate(CHANNELS):
        source = IbkrReadOnlyQuoteSource(
            host=args.host or settings.tws_host,
            port=args.port or settings.tws_port,
            client_id=args.client_id_base + index,
            timeout=args.timeout,
            snapshot=True,
            market_data_type=market_data_type,
            exchange=exchange,
        )
        cache = InMemoryQuoteCache()
        quotes = source.get_quotes(symbols)
        cache.update_many(quotes)
        returned_symbols = sorted(cache.snapshot())
        missing_symbols = [symbol for symbol in symbols if symbol not in returned_symbols]
        checks.append(
            {
                "channel": name,
                "exchange": exchange,
                "market_data_type": market_data_type,
                "ok": bool(quotes),
                "quote_count": len(quotes),
                "returned_symbols": returned_symbols,
                "missing_symbols": missing_symbols,
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
        )

    payload = {
        "source": "ibkr_market_data_diagnostics",
        "requested_symbols": symbols,
        "checks": checks,
        "best_channel": next((check["channel"] for check in checks if check["ok"]), None),
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
