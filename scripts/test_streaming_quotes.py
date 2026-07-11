"""Read-only smoke test for IBKR Level I streaming quotes.

This script subscribes only to configured symbols, prints the latest cache, then
cancels market-data subscriptions and disconnects. It never places orders.
"""

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.config import Settings
from trading.ibkr_streaming import IbkrStreamingQuoteSource


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--print-every", type=float, default=2.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = Settings.load()
    source = IbkrStreamingQuoteSource(
        symbols=settings.streaming_symbols,
        host=settings.streaming_tws_host,
        port=settings.streaming_tws_port,
        client_id=settings.streaming_client_id,
        stale_ms=settings.streaming_stale_ms,
        max_symbols=settings.streaming_max_symbols,
        market_data_type=1,
    )
    try:
        started = source.start(timeout=settings.tws_status_timeout)
        if not started:
            print(json.dumps({"status": "error", **source.report()}, indent=2, sort_keys=True))
            return 1
        deadline = time.monotonic() + max(0.0, args.seconds)
        while time.monotonic() < deadline:
            print(json.dumps({"status": "ok", **source.report()}, indent=2, sort_keys=True))
            time.sleep(max(0.1, args.print_every))
        print(json.dumps({"status": "complete", **source.report()}, indent=2, sort_keys=True))
        return 0
    finally:
        source.stop()


if __name__ == "__main__":
    raise SystemExit(main())
