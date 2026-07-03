from datetime import datetime, timedelta, timezone
import unittest

from trading.market_data import Bar, Quote
from trading.strategy_modules import (
    ConservativeTrendConfig,
    ConservativeTrendModule,
    ModuleDecision,
    ModulePosition,
    PortfolioRiskConfig,
    PortfolioRiskGate,
)


class ConservativeTrendModuleTests(unittest.TestCase):
    def test_module_buys_confirmed_classic_uptrend(self) -> None:
        now = datetime.now(timezone.utc)
        module = ConservativeTrendModule(
            ["AAPL"],
            ConservativeTrendConfig(
                fast_window=2,
                slow_window=3,
                min_gap_pct=0.0001,
                cooldown_steps=0,
            ),
        )
        bars = bars_for("AAPL", [100.0, 100.2, 100.5], now)
        quote = Quote(
            symbol="AAPL",
            last=100.55,
            bid=100.53,
            ask=100.57,
            timestamp=now,
            source="test",
        )

        decision = module.evaluate(symbol="AAPL", quote=quote, bars=bars, step=3)

        self.assertEqual(decision.action, "BUY")
        self.assertEqual(decision.side, "BUY")
        self.assertEqual(decision.limit_price, 100.57)

    def test_module_sells_after_profit_target(self) -> None:
        now = datetime.now(timezone.utc)
        module = ConservativeTrendModule(
            ["MSFT"],
            ConservativeTrendConfig(
                fast_window=2,
                slow_window=3,
                profit_target_pct=0.001,
                cooldown_steps=0,
            ),
        )
        buy_decision = module.evaluate(
            symbol="MSFT",
            quote=Quote("MSFT", 200.5, now, "test", bid=200.46, ask=200.54),
            bars=bars_for("MSFT", [200.0, 200.2, 200.5], now),
            step=3,
        )
        module.record_order_decision(buy_decision, step=3)

        sell_decision = module.evaluate(
            symbol="MSFT",
            quote=Quote("MSFT", 200.8, now, "test", bid=200.76, ask=200.84),
            bars=bars_for("MSFT", [200.2, 200.5, 200.8], now),
            step=4,
        )

        self.assertEqual(sell_decision.action, "SELL")
        self.assertEqual(sell_decision.side, "SELL")
        self.assertEqual(sell_decision.reason, "profit target reached")

    def test_module_blocks_unapproved_symbol(self) -> None:
        now = datetime.now(timezone.utc)
        module = ConservativeTrendModule(["AAPL"], ConservativeTrendConfig())

        decision = module.evaluate(
            symbol="TSLA",
            quote=Quote("TSLA", 250.0, now, "test", bid=249.95, ask=250.05),
            bars=bars_for("TSLA", [249.0, 249.5, 250.0, 250.3, 250.5], now),
            step=5,
        )

        self.assertEqual(decision.action, "HOLD")
        self.assertEqual(decision.reason, "symbol is not in the approved pool")

    def test_portfolio_risk_gate_blocks_extra_entry_after_position_limit(self) -> None:
        gate = PortfolioRiskGate(PortfolioRiskConfig(max_open_positions=1))
        now = datetime.now(timezone.utc)
        decision = ModuleDecision(
            "BUY",
            "MSFT",
            "test",
            side="BUY",
            quantity=1,
            limit_price=100.0,
        )

        result = gate.evaluate(
            decision,
            positions={"AAPL": ModulePosition("AAPL", 1, 100.0, 1)},
            latest_quotes={"AAPL": Quote("AAPL", 100.0, now, "test")},
            realized_pnl=0.0,
            consecutive_losses=0,
            now=now.replace(hour=14, minute=0),
        )

        self.assertFalse(result.approved)
        self.assertEqual(result.reason, "max open positions reached")

    def test_portfolio_risk_gate_blocks_daily_loss(self) -> None:
        gate = PortfolioRiskGate(PortfolioRiskConfig(max_daily_loss=10.0))
        now = datetime.now(timezone.utc).replace(hour=14, minute=0)
        decision = ModuleDecision(
            "BUY",
            "MSFT",
            "test",
            side="BUY",
            quantity=1,
            limit_price=100.0,
        )

        result = gate.evaluate(
            decision,
            positions={},
            latest_quotes={},
            realized_pnl=-10.0,
            consecutive_losses=0,
            now=now,
        )

        self.assertFalse(result.approved)
        self.assertEqual(result.reason, "daily loss limit reached")


def bars_for(symbol: str, closes: list[float], now: datetime) -> list[Bar]:
    bars = []
    for index, close in enumerate(closes):
        timestamp = now + timedelta(minutes=index)
        bars.append(
            Bar(
                symbol=symbol,
                interval_seconds=60,
                started_at=timestamp,
                ended_at=timestamp,
                open=close,
                high=close,
                low=close,
                close=close,
                volume=1000,
            )
        )
    return bars


if __name__ == "__main__":
    unittest.main()
