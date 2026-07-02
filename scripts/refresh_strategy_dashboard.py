"""Regenerate the static strategy dashboard on a timer.

This script only writes HTML. It does not place orders and does not change any
trading lock state.
"""

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.dashboard import render_dashboard_html
from trading.simulation import StrategySimulationConfig, run_strategy_simulation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="AAPL,MSFT,QQQ")
    parser.add_argument("--steps", type=int, default=1)
    parser.add_argument(
        "--source",
        choices=("simulated", "stooq", "yahoo", "yahoo-replay", "ibkr-readonly"),
        default="ibkr-readonly",
    )
    parser.add_argument("--interval-seconds", type=float, default=10.0)
    parser.add_argument(
        "--count",
        type=int,
        default=0,
        help="Number of refreshes. Use 0 to run until interrupted.",
    )
    parser.add_argument(
        "--output",
        default="dashboard/live_strategy_dashboard.html",
        help="HTML output path.",
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
    if args.interval_seconds <= 0:
        raise SystemExit("--interval-seconds must be positive")
    if args.count < 0:
        raise SystemExit("--count cannot be negative")

    symbols = [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()]
    output = PROJECT_ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)

    iteration = 0
    while True:
        iteration += 1
        data = run_strategy_simulation(
            StrategySimulationConfig(
                symbols=symbols,
                steps=args.steps,
                source=args.source,
                ibkr_host=args.ibkr_host,
                ibkr_port=args.ibkr_port,
                ibkr_client_id=args.ibkr_client_id,
                ibkr_timeout=args.ibkr_timeout,
                ibkr_market_data_type=args.ibkr_market_data_type,
                ibkr_exchange=args.ibkr_exchange,
            )
        )
        output.write_text(
            render_dashboard_html(
                data,
                auto_refresh_seconds=args.interval_seconds,
            ),
            encoding="utf-8",
        )
        print(f"[{iteration}] wrote {output}")

        if args.count and iteration >= args.count:
            return 0
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
