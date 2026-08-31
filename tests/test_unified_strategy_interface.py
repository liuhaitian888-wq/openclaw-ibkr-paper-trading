from datetime import datetime, timezone
import unittest

from execution.paper import live_order, paper_order
from risk.core import OrderRiskConfig, validate_order
from strategies import (
    DualMovingAverageStrategy,
    GridStrategy,
    LightGbmStyleBaselineStrategy,
    MarketData,
    PortfolioState,
    ZScoreMeanReversionStrategy,
)


class UnifiedStrategyInterfaceTests(unittest.TestCase):
    def test_dual_ma_generates_buy_signal(self) -> None:
        strategy = DualMovingAverageStrategy(fast_window=2, slow_window=3)
        signal = strategy.generate_signal(
            MarketData("AAPL", [100.0, 101.0, 103.0], datetime.now(timezone.utc), ask=103.05),
            PortfolioState(),
        )

        self.assertEqual(signal.action, "BUY")
        self.assertEqual(signal.symbol, "AAPL")
        self.assertEqual(signal.target_position, 1)

    def test_zscore_mean_reversion_generates_buy_signal(self) -> None:
        strategy = ZScoreMeanReversionStrategy(window=5, entry_z=1.0)
        signal = strategy.generate_signal(
            MarketData("MSFT", [100.0, 100.2, 100.1, 100.3, 98.0], datetime.now(timezone.utc), ask=98.05),
            PortfolioState(),
        )

        self.assertEqual(signal.action, "BUY")

    def test_grid_generates_sell_signal_for_upper_band(self) -> None:
        strategy = GridStrategy(reference_price=100.0, grid_pct=0.01)
        signal = strategy.generate_signal(
            MarketData("SPY", [102.0], datetime.now(timezone.utc), bid=101.95),
            PortfolioState(positions={"SPY": 2}),
        )

        self.assertEqual(signal.action, "SELL")
        self.assertLess(signal.target_position, 2)

    def test_ml_baseline_uses_precomputed_probability(self) -> None:
        strategy = LightGbmStyleBaselineStrategy(buy_threshold=0.55)
        signal = strategy.generate_signal(
            MarketData("AAPL", [100.0], features={"ml_up_probability": 0.6}),
            PortfolioState(),
        )

        self.assertEqual(signal.action, "BUY")

    def test_risk_and_paper_order_path(self) -> None:
        strategy = DualMovingAverageStrategy(fast_window=2, slow_window=3)
        state = PortfolioState()
        signal = strategy.generate_signal(MarketData("AAPL", [100.0, 101.0, 103.0], ask=103.05), state)
        risk_config = OrderRiskConfig(kill_switch_enabled=False)

        decision = validate_order(signal, state, risk_config)
        order = paper_order(signal, state.position_for(signal.symbol))

        self.assertTrue(decision.approved)
        self.assertEqual(order.status, "PAPER_ACCEPTED")
        self.assertEqual(order.quantity, 1)

    def test_live_order_is_disabled_by_default(self) -> None:
        signal = DualMovingAverageStrategy(fast_window=2, slow_window=3).generate_signal(
            MarketData("AAPL", [100.0, 101.0, 103.0], ask=103.05),
            PortfolioState(),
        )

        with self.assertRaises(PermissionError):
            live_order(signal, OrderRiskConfig(kill_switch_enabled=False))


if __name__ == "__main__":
    unittest.main()
