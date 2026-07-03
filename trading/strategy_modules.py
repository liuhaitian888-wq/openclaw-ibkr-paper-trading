from dataclasses import dataclass
from datetime import datetime
from statistics import mean
from typing import Dict, Literal, Optional, Sequence, Tuple

from trading.market_data import Bar, Quote
from trading.models import Side


ModuleAction = Literal["BUY", "SELL", "HOLD"]


@dataclass(frozen=True)
class ConservativeTrendConfig:
    fast_window: int = 3
    slow_window: int = 5
    profit_target_pct: float = 0.004
    stop_loss_pct: float = 0.003
    min_gap_pct: float = 0.0005
    max_spread_pct: float = 0.002
    max_quote_age_ms: float = 5000.0
    quantity: int = 1
    cooldown_steps: int = 1


@dataclass(frozen=True)
class ModulePosition:
    symbol: str
    quantity: int
    entry_price: float
    opened_step: int


@dataclass(frozen=True)
class ModuleDecision:
    action: ModuleAction
    symbol: str
    reason: str
    side: Optional[Side] = None
    quantity: int = 0
    limit_price: Optional[float] = None
    fast_ma: Optional[float] = None
    slow_ma: Optional[float] = None
    position_entry_price: Optional[float] = None

    @property
    def is_order(self) -> bool:
        return self.side is not None and self.limit_price is not None and self.quantity > 0


@dataclass(frozen=True)
class PortfolioRiskConfig:
    max_open_positions: int = 4
    max_symbol_market_value: float = 400.0
    max_gross_market_value: float = 1200.0
    max_daily_loss: float = 25.0
    max_consecutive_losses: int = 3
    allow_new_entries_outside_rth: bool = False
    regular_session_start: str = "09:30"
    regular_session_end: str = "16:00"


@dataclass(frozen=True)
class PortfolioRiskDecision:
    approved: bool
    reason: str


class PortfolioRiskGate:
    def __init__(self, config: PortfolioRiskConfig) -> None:
        self._config = config

    def evaluate(
        self,
        decision: ModuleDecision,
        *,
        positions: Dict[str, ModulePosition],
        latest_quotes: Dict[str, Quote],
        realized_pnl: float,
        consecutive_losses: int,
        now: Optional[datetime] = None,
    ) -> PortfolioRiskDecision:
        if not decision.is_order or decision.side is None or decision.limit_price is None:
            return PortfolioRiskDecision(True, "not an order")
        if decision.side == "SELL":
            if decision.symbol not in positions:
                return PortfolioRiskDecision(False, "sell requires an in-memory position")
            return PortfolioRiskDecision(True, "sell exits existing position")
        if realized_pnl <= -abs(self._config.max_daily_loss):
            return PortfolioRiskDecision(False, "daily loss limit reached")
        if consecutive_losses >= self._config.max_consecutive_losses:
            return PortfolioRiskDecision(False, "consecutive loss limit reached")
        if not self._config.allow_new_entries_outside_rth and not _is_regular_session(
            now or datetime.now(),
            self._config.regular_session_start,
            self._config.regular_session_end,
        ):
            return PortfolioRiskDecision(False, "new entries are blocked outside regular session")
        if decision.symbol not in positions and len(positions) >= self._config.max_open_positions:
            return PortfolioRiskDecision(False, "max open positions reached")

        order_value = decision.quantity * decision.limit_price
        current_symbol_value = _position_market_value(
            decision.symbol,
            positions,
            latest_quotes,
        )
        if current_symbol_value + order_value > self._config.max_symbol_market_value:
            return PortfolioRiskDecision(False, "symbol market value limit reached")

        gross_value = sum(
            _position_market_value(symbol, positions, latest_quotes)
            for symbol in positions
        )
        if gross_value + order_value > self._config.max_gross_market_value:
            return PortfolioRiskDecision(False, "gross market value limit reached")
        return PortfolioRiskDecision(True, "portfolio risk checks passed")


class ConservativeTrendModule:
    """Classic conservative trend module for a rotating long-only paper pool.

    Rules:
    - Buy only approved pool symbols.
    - Buy when fast SMA is above slow SMA and price is above slow SMA.
    - Sell an owned symbol on small target, small stop, or trend loss.
    - Keep one in-memory position per symbol so SELL only follows a BUY.
    """

    name = "classic_conservative_trend"

    def __init__(
        self,
        allowed_symbols: Sequence[str],
        config: ConservativeTrendConfig,
    ) -> None:
        if config.fast_window <= 0 or config.slow_window <= 0:
            raise ValueError("moving average windows must be positive")
        if config.fast_window >= config.slow_window:
            raise ValueError("fast_window must be less than slow_window")
        self._allowed_symbols = {symbol.upper() for symbol in allowed_symbols}
        self._config = config
        self._positions: Dict[str, ModulePosition] = {}
        self._last_order_step: Dict[str, int] = {}

    @property
    def positions(self) -> Dict[str, ModulePosition]:
        return dict(self._positions)

    def evaluate(
        self,
        *,
        symbol: str,
        quote: Quote,
        bars: Sequence[Bar],
        step: int,
    ) -> ModuleDecision:
        symbol = symbol.upper()
        closes = [bar.close for bar in bars]
        fast_ma, slow_ma = self._averages(closes)
        position = self._positions.get(symbol)

        blocked = self._common_block_reason(symbol, quote, step)
        if blocked is not None:
            return ModuleDecision("HOLD", symbol, blocked, fast_ma=fast_ma, slow_ma=slow_ma)

        if fast_ma is None or slow_ma is None:
            return ModuleDecision(
                "HOLD",
                symbol,
                "not enough bar history",
                fast_ma=fast_ma,
                slow_ma=slow_ma,
            )

        if position is not None:
            return self._exit_decision(symbol, quote, position, fast_ma, slow_ma)

        gap_pct = (fast_ma - slow_ma) / slow_ma if slow_ma else 0.0
        if fast_ma > slow_ma and quote.last > slow_ma and gap_pct >= self._config.min_gap_pct:
            limit_price = round(float(quote.ask or quote.midpoint or quote.last), 2)
            return ModuleDecision(
                "BUY",
                symbol,
                "fast SMA is above slow SMA and price confirms trend",
                side="BUY",
                quantity=self._config.quantity,
                limit_price=limit_price,
                fast_ma=fast_ma,
                slow_ma=slow_ma,
            )

        return ModuleDecision(
            "HOLD",
            symbol,
            "trend entry conditions are not met",
            fast_ma=fast_ma,
            slow_ma=slow_ma,
        )

    def record_order_decision(self, decision: ModuleDecision, step: int) -> None:
        if not decision.is_order or decision.side is None or decision.limit_price is None:
            return
        symbol = decision.symbol.upper()
        self._last_order_step[symbol] = step
        if decision.side == "BUY":
            self._positions[symbol] = ModulePosition(
                symbol=symbol,
                quantity=decision.quantity,
                entry_price=decision.limit_price,
                opened_step=step,
            )
            return
        self._positions.pop(symbol, None)

    def _exit_decision(
        self,
        symbol: str,
        quote: Quote,
        position: ModulePosition,
        fast_ma: float,
        slow_ma: float,
    ) -> ModuleDecision:
        target_price = position.entry_price * (1 + self._config.profit_target_pct)
        stop_price = position.entry_price * (1 - self._config.stop_loss_pct)
        exit_reason = None
        if quote.last >= target_price:
            exit_reason = "profit target reached"
        elif quote.last <= stop_price:
            exit_reason = "stop loss reached"
        elif fast_ma < slow_ma:
            exit_reason = "fast SMA fell below slow SMA"

        if exit_reason is None:
            return ModuleDecision(
                "HOLD",
                symbol,
                "holding existing paper position",
                fast_ma=fast_ma,
                slow_ma=slow_ma,
                position_entry_price=position.entry_price,
            )

        limit_price = round(float(quote.bid or quote.midpoint or quote.last), 2)
        return ModuleDecision(
            "SELL",
            symbol,
            exit_reason,
            side="SELL",
            quantity=position.quantity,
            limit_price=limit_price,
            fast_ma=fast_ma,
            slow_ma=slow_ma,
            position_entry_price=position.entry_price,
        )

    def _common_block_reason(
        self,
        symbol: str,
        quote: Quote,
        step: int,
    ) -> Optional[str]:
        if symbol not in self._allowed_symbols:
            return "symbol is not in the approved pool"
        if quote.age_ms() > self._config.max_quote_age_ms:
            return "quote is stale"
        if quote.spread is not None and quote.spread / quote.last > self._config.max_spread_pct:
            return "spread is too wide"
        last_step = self._last_order_step.get(symbol)
        if last_step is not None and step - last_step <= self._config.cooldown_steps:
            return "cooldown after prior module order"
        return None

    def _averages(self, closes: Sequence[float]) -> Tuple[Optional[float], Optional[float]]:
        if len(closes) < self._config.slow_window:
            fast = mean(closes[-self._config.fast_window :]) if len(closes) >= self._config.fast_window else None
            return fast, None
        return (
            mean(closes[-self._config.fast_window :]),
            mean(closes[-self._config.slow_window :]),
        )


def _position_market_value(
    symbol: str,
    positions: Dict[str, ModulePosition],
    latest_quotes: Dict[str, Quote],
) -> float:
    position = positions.get(symbol)
    if position is None:
        return 0.0
    quote = latest_quotes.get(symbol)
    price = quote.last if quote is not None else position.entry_price
    return position.quantity * price


def _is_regular_session(now: datetime, start: str, end: str) -> bool:
    current = now.time()
    start_time = datetime.strptime(start, "%H:%M").time()
    end_time = datetime.strptime(end, "%H:%M").time()
    return start_time <= current <= end_time
