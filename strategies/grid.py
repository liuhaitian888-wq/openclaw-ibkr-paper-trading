from strategies.base import MarketData, PortfolioState, Signal


class GridStrategy:
    name = "grid_rebalance"

    def __init__(self, reference_price: float, grid_pct: float = 0.005, max_position: int = 3) -> None:
        if reference_price <= 0:
            raise ValueError("reference_price must be positive")
        if grid_pct <= 0:
            raise ValueError("grid_pct must be positive")
        self.reference_price = reference_price
        self.grid_pct = grid_pct
        self.max_position = max_position

    def generate_signal(self, market_data: MarketData, portfolio_state: PortfolioState) -> Signal:
        symbol = market_data.symbol.upper()
        current = portfolio_state.position_for(symbol)
        deviation = (market_data.last - self.reference_price) / self.reference_price
        band = int(abs(deviation) / self.grid_pct)
        confidence = min(1.0, abs(deviation) / (self.grid_pct * max(1, self.max_position)))
        if deviation <= -self.grid_pct and current < self.max_position:
            target = min(self.max_position, max(current + 1, band))
            return Signal(symbol, "BUY", confidence, target, "price moved down one grid band", market_data.timestamp, self.name, market_data.ask or market_data.midpoint, {"deviation": deviation})
        if deviation >= self.grid_pct and current > 0:
            target = max(0, current - max(1, band))
            return Signal(symbol, "SELL", confidence, target, "price moved up one grid band", market_data.timestamp, self.name, market_data.bid or market_data.midpoint, {"deviation": deviation})
        return Signal(symbol, "HOLD", confidence, current, "price is inside grid hold zone", market_data.timestamp, self.name, metadata={"deviation": deviation})
