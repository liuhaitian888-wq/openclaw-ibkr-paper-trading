from statistics import mean, pstdev

from strategies.base import MarketData, PortfolioState, Signal


class ZScoreMeanReversionStrategy:
    name = "zscore_mean_reversion"

    def __init__(self, window: int = 20, entry_z: float = 2.0, exit_z: float = 0.25, target_quantity: int = 1) -> None:
        if window < 2:
            raise ValueError("window must be at least 2")
        self.window = window
        self.entry_z = abs(entry_z)
        self.exit_z = abs(exit_z)
        self.target_quantity = target_quantity

    def generate_signal(self, market_data: MarketData, portfolio_state: PortfolioState) -> Signal:
        symbol = market_data.symbol.upper()
        prices = [float(price) for price in market_data.prices]
        current = portfolio_state.position_for(symbol)
        if len(prices) < self.window:
            return Signal(symbol, "HOLD", 0.0, current, "not enough price history", market_data.timestamp, self.name)
        sample = prices[-self.window :]
        avg = mean(sample)
        sigma = pstdev(sample)
        if sigma == 0:
            return Signal(symbol, "HOLD", 0.0, current, "zero volatility window", market_data.timestamp, self.name)
        z_score = (prices[-1] - avg) / sigma
        confidence = min(1.0, abs(z_score) / max(self.entry_z, 1e-9))
        if z_score <= -self.entry_z and current <= 0:
            return Signal(symbol, "BUY", confidence, self.target_quantity, "price is below mean-reversion entry band", market_data.timestamp, self.name, market_data.ask or market_data.midpoint, {"z_score": z_score})
        if current > 0 and z_score >= -self.exit_z:
            return Signal(symbol, "SELL", confidence, 0, "price reverted toward mean", market_data.timestamp, self.name, market_data.bid or market_data.midpoint, {"z_score": z_score})
        return Signal(symbol, "HOLD", confidence, current, "z-score does not require action", market_data.timestamp, self.name, metadata={"z_score": z_score})
