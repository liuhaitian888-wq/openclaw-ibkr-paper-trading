from statistics import mean

from strategies.base import MarketData, PortfolioState, Signal


class DualMovingAverageStrategy:
    name = "dual_moving_average"

    def __init__(self, fast_window: int = 5, slow_window: int = 20, target_quantity: int = 1) -> None:
        if fast_window <= 0 or slow_window <= 0:
            raise ValueError("moving average windows must be positive")
        if fast_window >= slow_window:
            raise ValueError("fast_window must be less than slow_window")
        self.fast_window = fast_window
        self.slow_window = slow_window
        self.target_quantity = target_quantity

    def generate_signal(self, market_data: MarketData, portfolio_state: PortfolioState) -> Signal:
        symbol = market_data.symbol.upper()
        prices = [float(price) for price in market_data.prices]
        if len(prices) < self.slow_window:
            return Signal(symbol, "HOLD", 0.0, portfolio_state.position_for(symbol), "not enough price history", market_data.timestamp, self.name)

        fast = mean(prices[-self.fast_window :])
        slow = mean(prices[-self.slow_window :])
        current = portfolio_state.position_for(symbol)
        gap = (fast - slow) / slow if slow else 0.0
        if fast > slow and current <= 0:
            return Signal(symbol, "BUY", min(1.0, abs(gap) * 100), self.target_quantity, "fast MA crossed above slow MA", market_data.timestamp, self.name, market_data.ask or market_data.midpoint, {"fast_ma": fast, "slow_ma": slow})
        if fast < slow and current > 0:
            return Signal(symbol, "SELL", min(1.0, abs(gap) * 100), 0, "fast MA crossed below slow MA", market_data.timestamp, self.name, market_data.bid or market_data.midpoint, {"fast_ma": fast, "slow_ma": slow})
        return Signal(symbol, "HOLD", min(1.0, abs(gap) * 50), current, "moving averages do not require action", market_data.timestamp, self.name, metadata={"fast_ma": fast, "slow_ma": slow})
