"""Generate a local static strategy dashboard.

The dashboard is a static HTML file with embedded simulation data. It does not
connect to IBKR and does not place orders.
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.dashboard import render_dashboard_html
from trading.simulation import StrategySimulationConfig, run_strategy_simulation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="AAPL,MSFT,QQQ")
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument(
        "--batch-size",
        type=int,
        help="Number of symbols to request per scan step. Defaults to all symbols.",
    )
    parser.add_argument(
        "--source",
        choices=("simulated", "stooq", "yahoo", "yahoo-replay", "ibkr-readonly"),
        default="simulated",
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
    parser.add_argument(
        "--output",
        default="dashboard/strategy_dashboard.html",
        help="HTML output path.",
    )
    parser.add_argument(
        "--auto-refresh-seconds",
        type=float,
        default=0.0,
        help="Add browser auto-refresh to the generated HTML. Use 0 to disable.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    symbols = [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()]
    data = run_strategy_simulation(
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
    output = PROJECT_ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_dashboard_html(
            data,
            auto_refresh_seconds=args.auto_refresh_seconds or None,
        ),
        encoding="utf-8",
    )
    print(str(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
