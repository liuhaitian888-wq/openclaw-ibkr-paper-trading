"""Run a local paper-only strategy simulation.

This command does not connect to IBKR and does not place orders. It exercises the
market-data cache, bar builder, value filter, moving-average signal engine, and
tactical entry planner so the framework can evolve safely.
"""

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.simulation import StrategySimulationConfig, run_strategy_simulation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="AAPL,MSFT")
    parser.add_argument("--steps", type=int, default=12)
    parser.add_argument(
        "--batch-size",
        type=int,
        help="Number of symbols to request per scan step. Defaults to all symbols.",
    )
    parser.add_argument("--poll-seconds", type=float, default=0.0)
    parser.add_argument(
        "--source",
        choices=("simulated", "stooq", "yahoo", "yahoo-replay", "ibkr-readonly"),
        default="simulated",
        help="Quote source. External free sources are delayed/keyless and for early framework tests only.",
    )
    parser.add_argument("--ibkr-host")
    parser.add_argument("--ibkr-port", type=int)
    parser.add_argument("--ibkr-client-id", type=int)
    parser.add_argument("--ibkr-timeout", type=float, default=5.0)
    parser.add_argument(
        "--ibkr-exchange",
        default="SMART",
        help="IBKR contract exchange, for example SMART or IEX.",
    )
    parser.add_argument(
        "--ibkr-market-data-type",
        type=int,
        default=3,
        help="IBKR market data type: 1 real-time, 3 delayed, 4 delayed-frozen.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    symbols = [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()]
    result = run_strategy_simulation(
        StrategySimulationConfig(
            symbols=symbols,
            steps=args.steps,
            batch_size=args.batch_size,
            source=args.source,
            ibkr_host=args.ibkr_host,
            ibkr_port=args.ibkr_port,
            ibkr_client_id=args.ibkr_client_id,
            ibkr_timeout=args.ibkr_timeout,
            ibkr_market_data_type=args.ibkr_market_data_type,
            ibkr_exchange=args.ibkr_exchange,
        )
    )
    if args.poll_seconds > 0:
        time.sleep(args.poll_seconds)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
