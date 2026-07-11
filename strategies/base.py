from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Literal, Mapping, Sequence


Action = Literal["BUY", "SELL", "HOLD"]


@dataclass(frozen=True)
class MarketData:
    symbol: str
    prices: Sequence[float]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    bid: float | None = None
    ask: float | None = None
    features: Mapping[str, float] = field(default_factory=dict)

    @property
    def last(self) -> float:
        if not self.prices:
            raise ValueError("prices must not be empty")
        return float(self.prices[-1])

    @property
    def midpoint(self) -> float:
        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / 2
        return self.last


@dataclass(frozen=True)
class PortfolioState:
    cash: float = 100_000.0
    positions: Mapping[str, int] = field(default_factory=dict)
    equity: float = 100_000.0
    realized_pnl: float = 0.0
    open_orders: int = 0

    def position_for(self, symbol: str) -> int:
        return int(self.positions.get(symbol.upper(), 0))


@dataclass(frozen=True)
class Signal:
    symbol: str
    action: Action
    confidence: float
    target_position: int
    reason: str
    timestamp: datetime
    strategy_name: str
    limit_price: float | None = None
    metadata: Dict[str, float | str | int] = field(default_factory=dict)
