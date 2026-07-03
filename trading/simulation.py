from dataclasses import dataclass
from typing import Dict, List, Optional

from trading.config import Settings
from trading.ibkr_readonly import IbkrReadOnlyQuoteSource, ParallelIbkrReadOnlyQuoteSource
from trading.market_data import (
    QuoteSource,
    SimulatedQuoteSource,
    StooqDelayedQuoteSource,
    YahooChartReplayQuoteSource,
    YahooDelayedQuoteSource,
)
from trading.strategy import (
    CandidateProfile,
    MovingAverageConfig,
    RotatingStrategyScanner,
    StrategyScannerConfig,
    TacticalRiskConfig,
    ValueFilterConfig,
    ValuePoolFilter,
)


@dataclass(frozen=True)
class StrategySimulationConfig:
    symbols: List[str]
    steps: int = 12
    source: str = "simulated"
    interval_seconds: int = 1
    batch_size: Optional[int] = None
    ibkr_host: Optional[str] = None
    ibkr_port: Optional[int] = None
    ibkr_client_id: Optional[int] = None
    ibkr_timeout: float = 5.0
    ibkr_market_data_type: int = 3
    ibkr_exchange: str = "SMART"
    ibkr_workers: int = 1
    ibkr_symbols_per_worker: int = 8


def run_strategy_simulation(config: StrategySimulationConfig) -> Dict[str, object]:
    symbols = [symbol.strip().upper() for symbol in config.symbols if symbol.strip()]
    source = quote_source(config)
    value_filter = ValuePoolFilter(ValueFilterConfig())
    value_pool = [value_pool_record(value_filter, profile) for profile in default_profiles()]
    allowed_symbols = [
        item["symbol"]
        for item in value_pool
        if item["approved"] is True
    ]
    batch_size = config.batch_size or max(1, len(symbols))
    scanner = RotatingStrategyScanner(
        source=source,
        symbols=symbols,
        allowed_symbols=allowed_symbols,
        config=StrategyScannerConfig(
            batch_size=batch_size,
            interval_seconds=config.interval_seconds,
            moving_average=MovingAverageConfig(
                short_window=2,
                long_window=4,
                confirmation_bars=2,
            ),
            tactical_risk=TacticalRiskConfig(max_quote_age_ms=5000.0),
        ),
    )

    events: List[Dict[str, object]] = []
    scan_reports: List[Dict[str, object]] = []
    for step in range(max(1, config.steps)):
        scan_report = scanner.scan_once()
        scan_reports.append(
            {
                "step": step,
                "requested_symbols": scan_report["requested_symbols"],
                "returned_symbols": scan_report["returned_symbols"],
                "missing_symbols": scan_report["missing_symbols"],
            }
        )
        for event in scan_report["events"]:
            event["step"] = step
            events.append(event)

    cache_snapshot = scanner.cache.snapshot()
    returned_symbols = sorted(cache_snapshot)
    missing_symbols = [symbol for symbol in symbols if symbol not in returned_symbols]

    return {
        "source": config.source,
        "symbols": symbols,
        "batch_size": batch_size,
        "returned_symbols": returned_symbols,
        "missing_symbols": missing_symbols,
        "feed_errors": list(getattr(source, "last_errors", [])),
        "value_pool": value_pool,
        "allowed_symbols": allowed_symbols,
        "events": events,
        "scan_reports": scan_reports,
        "cache": [
            {
                "symbol": quote.symbol,
                "last": quote.last,
                "bid": quote.bid,
                "ask": quote.ask,
                "close": quote.close,
                "volume": quote.volume,
                "age_ms": quote.age_ms(),
                "source": quote.source,
                "timestamp": quote.timestamp.isoformat(),
            }
            for quote in cache_snapshot.values()
        ],
    }


def quote_source(config: StrategySimulationConfig) -> QuoteSource:
    source_name = config.source
    if source_name == "stooq":
        return StooqDelayedQuoteSource()
    if source_name == "yahoo":
        return YahooDelayedQuoteSource()
    if source_name == "yahoo-replay":
        return YahooChartReplayQuoteSource()
    if source_name == "ibkr-readonly":
        settings = None
        if (
            config.ibkr_host is None
            or config.ibkr_port is None
            or config.ibkr_client_id is None
        ):
            settings = Settings.load()
        if config.ibkr_workers > 1:
            return ParallelIbkrReadOnlyQuoteSource(
                host=config.ibkr_host or settings.tws_host,
                port=config.ibkr_port or settings.tws_port,
                client_id=config.ibkr_client_id or settings.tws_client_id + 100,
                timeout=config.ibkr_timeout,
                snapshot=True,
                market_data_type=config.ibkr_market_data_type,
                exchange=config.ibkr_exchange,
                workers=config.ibkr_workers,
                symbols_per_worker=config.ibkr_symbols_per_worker,
            )
        return IbkrReadOnlyQuoteSource(
            host=config.ibkr_host or settings.tws_host,
            port=config.ibkr_port or settings.tws_port,
            client_id=config.ibkr_client_id or settings.tws_client_id + 100,
            timeout=config.ibkr_timeout,
            snapshot=True,
            market_data_type=config.ibkr_market_data_type,
            exchange=config.ibkr_exchange,
        )
    symbols = [symbol.strip().upper() for symbol in config.symbols if symbol.strip()]
    return SimulatedQuoteSource(default_prices(symbols))


def default_prices(symbols: List[str]) -> Dict[str, List[float]]:
    defaults = {
        "AAPL": [100.0, 100.1, 100.15, 100.25, 100.35, 100.55, 100.7, 100.8],
        "MSFT": [200.0, 200.02, 200.05, 200.12, 200.2, 200.35, 200.5, 200.7],
        "QQQ": [500.0, 500.1, 500.2, 500.32, 500.48, 500.72, 500.9, 501.1],
    }
    return {
        symbol: defaults.get(
            symbol,
            [50.0, 50.02, 50.04, 50.08, 50.13, 50.21, 50.34, 50.55],
        )
        for symbol in symbols
    }


def default_profiles() -> List[CandidateProfile]:
    return [
        CandidateProfile(
            "AAPL",
            pe_ratio=28.0,
            forward_pe=24.0,
            peg_ratio=1.8,
            price_to_free_cash_flow=27.0,
            debt_to_equity=1.4,
            revenue_growth_yoy=0.03,
            gross_margin=0.46,
            operating_margin=0.3,
            return_on_invested_capital=0.25,
            free_cash_flow_positive=True,
            earnings_positive=True,
            analyst_revision_positive=True,
            average_volume=40_000_000,
        ),
        CandidateProfile(
            "MSFT",
            pe_ratio=29.0,
            forward_pe=27.0,
            peg_ratio=1.9,
            price_to_free_cash_flow=30.0,
            debt_to_equity=0.6,
            revenue_growth_yoy=0.08,
            gross_margin=0.69,
            operating_margin=0.45,
            return_on_invested_capital=0.28,
            free_cash_flow_positive=True,
            earnings_positive=True,
            analyst_revision_positive=True,
            average_volume=20_000_000,
        ),
        CandidateProfile(
            "QQQ",
            free_cash_flow_positive=True,
            earnings_positive=True,
            average_volume=30_000_000,
        ),
    ]


def value_pool_record(
    value_filter: ValuePoolFilter,
    profile: CandidateProfile,
) -> Dict[str, object]:
    result = value_filter.evaluate(profile)
    return {
        "symbol": profile.symbol,
        "approved": result.approved,
        "score": result.score,
        "score_breakdown": result.score_breakdown,
        "reasons": list(result.reasons),
        "profile": {
            "pe_ratio": profile.pe_ratio,
            "forward_pe": profile.forward_pe,
            "peg_ratio": profile.peg_ratio,
            "price_to_free_cash_flow": profile.price_to_free_cash_flow,
            "debt_to_equity": profile.debt_to_equity,
            "revenue_growth_yoy": profile.revenue_growth_yoy,
            "gross_margin": profile.gross_margin,
            "operating_margin": profile.operating_margin,
            "return_on_invested_capital": profile.return_on_invested_capital,
            "average_volume": profile.average_volume,
        },
    }
