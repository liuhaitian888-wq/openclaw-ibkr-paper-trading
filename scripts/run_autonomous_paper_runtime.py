#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.autonomous_runtime import AutonomousRuntimeConfig, build_runtime
from trading.config import Settings
from trading.ibkr_readonly import IbkrReadOnlyQuoteSource
from trading.process_guard import ExecutionLock
from trading.strategy import MovingAverageConfig, RotatingStrategyScanner, StrategyScannerConfig, TacticalRiskConfig


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the session-aware autonomous IBKR paper runtime.")
    parser.add_argument("--symbols", default="AAPL,MSFT,SPY")
    parser.add_argument("--cycles", type=int)
    parser.add_argument("--sleep-seconds", type=float)
    parser.add_argument("--batch-size", type=int, default=3)
    parser.add_argument("--bar-interval-seconds", type=int, default=30)
    parser.add_argument("--market-data-type", type=int, default=3)
    args = parser.parse_args()

    settings = Settings.load()
    runtime_config = AutonomousRuntimeConfig.from_env()
    if args.cycles is not None:
        runtime_config = _replace(runtime_config, max_cycles=args.cycles)
    if args.sleep_seconds is not None:
        runtime_config = _replace(runtime_config, cycle_sleep_seconds=args.sleep_seconds)

    source = IbkrReadOnlyQuoteSource(
        host=settings.tws_host,
        port=settings.tws_port,
        client_id=settings.tws_client_id + 700,
        snapshot=True,
        market_data_type=args.market_data_type,
    )
    symbols = [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()]
    scanner = RotatingStrategyScanner(
        source=source,
        symbols=symbols,
        allowed_symbols=sorted(settings.allowed_symbols.intersection(symbols)),
        config=StrategyScannerConfig(
            batch_size=args.batch_size,
            interval_seconds=args.bar_interval_seconds,
            moving_average=MovingAverageConfig(short_window=1, long_window=2, confirmation_bars=1),
            tactical_risk=TacticalRiskConfig(
                max_quote_age_ms=10_000.0,
                max_spread_pct=0.003,
                quantity=min(1, settings.max_quantity),
            ),
        ),
    )
    with ExecutionLock(
        process_name="autonomous_paper_runtime",
        mode="paper",
        can_submit_orders=True,
        prefer_mode9=True,
    ):
        report = build_runtime(scanner=scanner, settings=settings, config=runtime_config).run_forever()
    print(report)
    return 0


def _replace(config: AutonomousRuntimeConfig, **updates: object) -> AutonomousRuntimeConfig:
    values = config.__dict__.copy()
    values.update(updates)
    return AutonomousRuntimeConfig(**values)


if __name__ == "__main__":
    raise SystemExit(main())
