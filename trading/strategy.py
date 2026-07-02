from dataclasses import dataclass
from statistics import mean
from typing import Dict, Iterable, List, Literal, Optional, Sequence, Tuple

from trading.market_data import (
    Bar,
    BarBuilder,
    InMemoryQuoteCache,
    Quote,
    QuoteSource,
    RotatingSymbolPool,
    SymbolRingBuffers,
)
from trading.models import Side, TradeProposal


SignalAction = Literal["ENTER_LONG", "EXIT_LONG", "HOLD"]


@dataclass(frozen=True)
class CandidateProfile:
    symbol: str
    pe_ratio: Optional[float] = None
    forward_pe: Optional[float] = None
    peg_ratio: Optional[float] = None
    price_to_free_cash_flow: Optional[float] = None
    debt_to_equity: Optional[float] = None
    revenue_growth_yoy: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    return_on_invested_capital: Optional[float] = None
    free_cash_flow_positive: bool = True
    earnings_positive: bool = True
    analyst_revision_positive: Optional[bool] = None
    average_volume: Optional[int] = None


@dataclass(frozen=True)
class ValueFilterConfig:
    max_pe: float = 30.0
    max_forward_pe: float = 28.0
    max_peg: float = 2.0
    max_price_to_free_cash_flow: float = 35.0
    max_debt_to_equity: float = 2.0
    min_revenue_growth_yoy: float = -0.05
    min_gross_margin: float = 0.25
    min_operating_margin: float = 0.05
    min_return_on_invested_capital: float = 0.08
    min_average_volume: int = 1_000_000
    min_score: float = 60.0


@dataclass(frozen=True)
class FilterResult:
    approved: bool
    reasons: Tuple[str, ...]
    score: float = 0.0
    score_breakdown: Optional[Dict[str, float]] = None


class ValuePoolFilter:
    def __init__(self, config: ValueFilterConfig) -> None:
        self._config = config

    def evaluate(self, profile: CandidateProfile) -> FilterResult:
        reasons = []
        if profile.pe_ratio is not None and profile.pe_ratio > self._config.max_pe:
            reasons.append("pe_ratio above limit")
        if profile.forward_pe is not None and profile.forward_pe > self._config.max_forward_pe:
            reasons.append("forward_pe above limit")
        if profile.peg_ratio is not None and profile.peg_ratio > self._config.max_peg:
            reasons.append("peg_ratio above limit")
        if (
            profile.price_to_free_cash_flow is not None
            and profile.price_to_free_cash_flow > self._config.max_price_to_free_cash_flow
        ):
            reasons.append("price_to_free_cash_flow above limit")
        if (
            profile.debt_to_equity is not None
            and profile.debt_to_equity > self._config.max_debt_to_equity
        ):
            reasons.append("debt_to_equity above limit")
        if (
            profile.revenue_growth_yoy is not None
            and profile.revenue_growth_yoy < self._config.min_revenue_growth_yoy
        ):
            reasons.append("revenue_growth_yoy below limit")
        if (
            profile.gross_margin is not None
            and profile.gross_margin < self._config.min_gross_margin
        ):
            reasons.append("gross_margin below limit")
        if (
            profile.operating_margin is not None
            and profile.operating_margin < self._config.min_operating_margin
        ):
            reasons.append("operating_margin below limit")
        if (
            profile.return_on_invested_capital is not None
            and profile.return_on_invested_capital < self._config.min_return_on_invested_capital
        ):
            reasons.append("return_on_invested_capital below limit")
        if not profile.free_cash_flow_positive:
            reasons.append("free cash flow is not positive")
        if not profile.earnings_positive:
            reasons.append("earnings are not positive")
        if (
            profile.average_volume is not None
            and profile.average_volume < self._config.min_average_volume
        ):
            reasons.append("average volume below limit")
        score, breakdown = self.score(profile)
        if score < self._config.min_score:
            reasons.append("value score below limit")
        return FilterResult(not reasons, tuple(reasons), score, breakdown)

    def score(self, profile: CandidateProfile) -> Tuple[float, Dict[str, float]]:
        valuation = _average_available(
            [
                _lower_is_better(profile.pe_ratio, excellent=15.0, poor=40.0),
                _lower_is_better(profile.forward_pe, excellent=15.0, poor=35.0),
                _lower_is_better(profile.peg_ratio, excellent=1.0, poor=3.0),
                _lower_is_better(
                    profile.price_to_free_cash_flow,
                    excellent=15.0,
                    poor=45.0,
                ),
            ],
            default=50.0,
        )
        quality = _average_available(
            [
                _higher_is_better(profile.gross_margin, excellent=0.65, poor=0.2),
                _higher_is_better(profile.operating_margin, excellent=0.3, poor=0.02),
                _higher_is_better(
                    profile.return_on_invested_capital,
                    excellent=0.25,
                    poor=0.03,
                ),
                100.0 if profile.free_cash_flow_positive else 0.0,
                100.0 if profile.earnings_positive else 0.0,
            ],
            default=50.0,
        )
        demand = _average_available(
            [
                _higher_is_better(
                    profile.revenue_growth_yoy,
                    excellent=0.2,
                    poor=-0.1,
                ),
                75.0 if profile.analyst_revision_positive is True else None,
                25.0 if profile.analyst_revision_positive is False else None,
            ],
            default=50.0,
        )
        safety = _average_available(
            [
                _lower_is_better(profile.debt_to_equity, excellent=0.4, poor=3.0),
                _higher_is_better(
                    None if profile.average_volume is None else float(profile.average_volume),
                    excellent=10_000_000.0,
                    poor=500_000.0,
                ),
            ],
            default=50.0,
        )
        breakdown = {
            "valuation": round(valuation, 3),
            "quality": round(quality, 3),
            "demand": round(demand, 3),
            "safety": round(safety, 3),
        }
        total = (
            valuation * 0.35
            + quality * 0.3
            + demand * 0.2
            + safety * 0.15
        )
        return round(total, 3), breakdown

    def approved_symbols(self, profiles: Iterable[CandidateProfile]) -> List[str]:
        return [
            profile.symbol.upper()
            for profile in profiles
            if self.evaluate(profile).approved
        ]


@dataclass(frozen=True)
class MovingAverageConfig:
    short_window: int = 3
    long_window: int = 5
    confirmation_bars: int = 2
    min_slope: float = 0.0
    min_gap_pct: float = 0.0005


@dataclass(frozen=True)
class SignalDecision:
    action: SignalAction
    symbol: str
    reason: str
    short_ma: Optional[float] = None
    long_ma: Optional[float] = None
    confidence: float = 0.0


class MovingAverageSignalEngine:
    def __init__(self, config: MovingAverageConfig) -> None:
        if config.short_window <= 0 or config.long_window <= 0:
            raise ValueError("moving average windows must be positive")
        if config.short_window >= config.long_window:
            raise ValueError("short_window must be less than long_window")
        self._config = config
        self._closes: Dict[str, List[float]] = {}
        self._confirmed: Dict[str, int] = {}
        self._entry_emitted: Dict[str, bool] = {}

    def update(self, bar: Bar) -> SignalDecision:
        symbol = bar.symbol.upper()
        closes = self._closes.setdefault(symbol, [])
        closes.append(bar.close)
        max_len = self._config.long_window + 2
        if len(closes) > max_len:
            del closes[:-max_len]
        if len(closes) < self._config.long_window:
            return SignalDecision("HOLD", symbol, "not enough bars")

        short_ma = mean(closes[-self._config.short_window :])
        long_ma = mean(closes[-self._config.long_window :])
        previous_short = mean(closes[-self._config.short_window - 1 : -1])
        slope = short_ma - previous_short
        gap_pct = (short_ma - long_ma) / long_ma if long_ma else 0.0

        if short_ma > long_ma and slope > self._config.min_slope and gap_pct >= self._config.min_gap_pct:
            count = self._confirmed.get(symbol, 0) + 1
            self._confirmed[symbol] = count
            if count >= self._config.confirmation_bars:
                if self._entry_emitted.get(symbol, False):
                    return SignalDecision(
                        "HOLD",
                        symbol,
                        "entry signal already emitted for this trend",
                        short_ma,
                        long_ma,
                    )
                self._entry_emitted[symbol] = True
                confidence = min(1.0, 0.5 + gap_pct * 100)
                return SignalDecision(
                    "ENTER_LONG",
                    symbol,
                    "short moving average is confirmed above long moving average",
                    short_ma,
                    long_ma,
                    confidence,
                )
            return SignalDecision(
                "HOLD",
                symbol,
                "moving average cross is waiting for confirmation",
                short_ma,
                long_ma,
            )

        self._confirmed[symbol] = 0
        self._entry_emitted[symbol] = False
        return SignalDecision(
            "HOLD",
            symbol,
            "moving average entry conditions are not met",
            short_ma,
            long_ma,
        )


@dataclass(frozen=True)
class TacticalRiskConfig:
    max_quote_age_ms: float = 1000.0
    max_spread_pct: float = 0.0015
    profit_target_pct: float = 0.01
    stop_loss_pct: float = 0.004
    quantity: int = 1


@dataclass(frozen=True)
class StrategyPlan:
    approved: bool
    reason: str
    proposal: Optional[TradeProposal] = None
    profit_target_price: Optional[float] = None
    stop_loss_price: Optional[float] = None


@dataclass(frozen=True)
class StrategyScannerConfig:
    batch_size: int = 8
    interval_seconds: int = 60
    bar_history_capacity: int = 128
    moving_average: MovingAverageConfig = MovingAverageConfig()
    tactical_risk: TacticalRiskConfig = TacticalRiskConfig(max_quote_age_ms=5000.0)


@dataclass(frozen=True)
class StrategyScanEvent:
    symbol: str
    quote: Quote
    signal: SignalDecision
    plan: StrategyPlan
    bar: Optional[Bar]

    def as_dict(self) -> Dict[str, object]:
        payload: Dict[str, object] = {
            "symbol": self.symbol,
            "price": self.quote.last,
            "quote_source": self.quote.source,
            "quote_age_ms": self.quote.age_ms(),
            "bid": self.quote.bid,
            "ask": self.quote.ask,
            "spread": self.quote.spread,
            "signal": self.signal.action,
            "signal_reason": self.signal.reason,
            "short_ma": self.signal.short_ma,
            "long_ma": self.signal.long_ma,
            "confidence": self.signal.confidence,
            "plan_approved": self.plan.approved,
            "plan_reason": self.plan.reason,
        }
        if self.bar is not None:
            payload["bar"] = {
                "interval_seconds": self.bar.interval_seconds,
                "started_at": self.bar.started_at.isoformat(),
                "ended_at": self.bar.ended_at.isoformat(),
                "open": self.bar.open,
                "high": self.bar.high,
                "low": self.bar.low,
                "close": self.bar.close,
                "volume": self.bar.volume,
            }
        if self.plan.proposal is not None:
            payload["proposal"] = {
                "idempotency_key": self.plan.proposal.idempotency_key,
                "symbol": self.plan.proposal.symbol,
                "side": self.plan.proposal.side,
                "quantity": self.plan.proposal.quantity,
                "limit_price": self.plan.proposal.limit_price,
                "stop_price": self.plan.proposal.stop_price,
                "profit_target_price": self.plan.profit_target_price,
            }
        return payload


class RotatingStrategyScanner:
    """Scan a large universe with one quote source and a fixed-size rotation."""

    def __init__(
        self,
        source: QuoteSource,
        symbols: Sequence[str],
        allowed_symbols: Sequence[str],
        config: StrategyScannerConfig,
    ) -> None:
        self._source = source
        self._pool = RotatingSymbolPool(symbols, config.batch_size)
        self._cache = InMemoryQuoteCache()
        self._bar_builder = BarBuilder(config.interval_seconds)
        self._bar_history: SymbolRingBuffers[Bar] = SymbolRingBuffers(
            config.bar_history_capacity
        )
        self._signal_engine = MovingAverageSignalEngine(config.moving_average)
        self._strategy = TacticalLongStrategy(allowed_symbols, config.tactical_risk)

    @property
    def cache(self) -> InMemoryQuoteCache:
        return self._cache

    @property
    def bar_history(self) -> SymbolRingBuffers[Bar]:
        return self._bar_history

    def scan_once(self) -> Dict[str, object]:
        requested_symbols = self._pool.next_batch()
        quotes = self._source.get_quotes(requested_symbols)
        self._cache.update_many(quotes)

        events = []
        for quote in quotes:
            closed_bar = self._bar_builder.update(quote)
            bar = closed_bar or self._bar_builder.active_bar(quote.symbol)
            if bar is not None:
                self._record_bar(bar)
                signal = self._signal_engine.update(bar)
            else:
                signal = SignalDecision("HOLD", quote.symbol.upper(), "not enough quotes")
            plan = self._strategy.plan_entry(signal, quote)
            events.append(
                StrategyScanEvent(
                    symbol=quote.symbol.upper(),
                    quote=quote,
                    signal=signal,
                    plan=plan,
                    bar=bar,
                )
            )

        returned_symbols = sorted({quote.symbol.upper() for quote in quotes})
        return {
            "requested_symbols": requested_symbols,
            "returned_symbols": returned_symbols,
            "missing_symbols": [
                symbol for symbol in requested_symbols if symbol not in returned_symbols
            ],
            "events": [event.as_dict() for event in events],
            "cache_symbols": sorted(self._cache.snapshot()),
            "bar_history_lengths": {
                symbol: len(self._bar_history.values(symbol))
                for symbol in self._pool.symbols
            },
            "feed_errors": list(getattr(self._source, "last_errors", [])),
        }

    def _record_bar(self, bar: Bar) -> None:
        latest = self._bar_history.latest(bar.symbol)
        if latest is not None and latest.started_at == bar.started_at:
            self._bar_history.replace_latest(bar.symbol, bar)
            return
        self._bar_history.append(bar.symbol, bar)


class TacticalLongStrategy:
    def __init__(
        self,
        allowed_symbols: Sequence[str],
        risk_config: TacticalRiskConfig,
    ) -> None:
        self._allowed_symbols = {symbol.upper() for symbol in allowed_symbols}
        self._risk = risk_config

    def plan_entry(self, signal: SignalDecision, quote: Quote) -> StrategyPlan:
        symbol = signal.symbol.upper()
        if signal.action != "ENTER_LONG":
            return StrategyPlan(False, signal.reason)
        if symbol not in self._allowed_symbols:
            return StrategyPlan(False, "symbol is not in the value-approved pool")
        if quote.age_ms() > self._risk.max_quote_age_ms:
            return StrategyPlan(False, "quote is stale")
        spread = quote.spread
        if spread is not None and spread / quote.last > self._risk.max_spread_pct:
            return StrategyPlan(False, "spread is too wide")

        limit_price = quote.ask if quote.ask is not None else quote.last
        stop_loss_price = round(limit_price * (1 - self._risk.stop_loss_pct), 4)
        profit_target_price = round(limit_price * (1 + self._risk.profit_target_pct), 4)
        idempotency_key = f"signal-{symbol.lower()}-{int(quote.timestamp.timestamp() * 1000)}"
        return StrategyPlan(
            approved=True,
            reason=signal.reason,
            proposal=TradeProposal(
                symbol=symbol,
                side="BUY",
                quantity=self._risk.quantity,
                limit_price=round(limit_price, 4),
                stop_price=stop_loss_price,
                idempotency_key=idempotency_key,
            ),
            profit_target_price=profit_target_price,
            stop_loss_price=stop_loss_price,
        )


def _average_available(values: Sequence[Optional[float]], default: float) -> float:
    available = [value for value in values if value is not None]
    if not available:
        return default
    return sum(available) / len(available)


def _lower_is_better(
    value: Optional[float],
    *,
    excellent: float,
    poor: float,
) -> Optional[float]:
    if value is None:
        return None
    if value <= excellent:
        return 100.0
    if value >= poor:
        return 0.0
    return 100.0 * (poor - value) / (poor - excellent)


def _higher_is_better(
    value: Optional[float],
    *,
    excellent: float,
    poor: float,
) -> Optional[float]:
    if value is None:
        return None
    if value >= excellent:
        return 100.0
    if value <= poor:
        return 0.0
    return 100.0 * (value - poor) / (excellent - poor)
