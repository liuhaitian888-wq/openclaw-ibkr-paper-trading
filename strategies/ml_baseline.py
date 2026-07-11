from strategies.base import MarketData, PortfolioState, Signal


class LightGbmStyleBaselineStrategy:
    """Lightweight stand-in for the first ML MVP signal.

    The production version should load a trained LightGBM model. This class keeps
    the runtime dependency-free for paper wiring by consuming a precomputed
    probability feature named ``ml_up_probability``.
    """

    name = "lightgbm_style_baseline"

    def __init__(self, buy_threshold: float = 0.58, sell_threshold: float = 0.42, target_quantity: int = 1) -> None:
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self.target_quantity = target_quantity

    def generate_signal(self, market_data: MarketData, portfolio_state: PortfolioState) -> Signal:
        symbol = market_data.symbol.upper()
        current = portfolio_state.position_for(symbol)
        probability = float(market_data.features.get("ml_up_probability", 0.5))
        confidence = min(1.0, abs(probability - 0.5) * 2)
        if probability >= self.buy_threshold and current <= 0:
            return Signal(symbol, "BUY", confidence, self.target_quantity, "ML baseline probability is above buy threshold", market_data.timestamp, self.name, market_data.ask or market_data.midpoint, {"ml_up_probability": probability})
        if probability <= self.sell_threshold and current > 0:
            return Signal(symbol, "SELL", confidence, 0, "ML baseline probability is below sell threshold", market_data.timestamp, self.name, market_data.bid or market_data.midpoint, {"ml_up_probability": probability})
        return Signal(symbol, "HOLD", confidence, current, "ML baseline probability is inside hold band", market_data.timestamp, self.name, metadata={"ml_up_probability": probability})
