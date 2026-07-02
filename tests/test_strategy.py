from datetime import datetime, timedelta, timezone
import unittest

from trading.market_data import (
    Bar,
    InMemoryQuoteCache,
    Quote,
    RingBuffer,
    RotatingSymbolPool,
    SimulatedQuoteSource,
    YahooDelayedQuoteSource,
)
from trading.strategy import (
    CandidateProfile,
    MovingAverageConfig,
    MovingAverageSignalEngine,
    RotatingStrategyScanner,
    StrategyScannerConfig,
    TacticalLongStrategy,
    TacticalRiskConfig,
    ValueFilterConfig,
    ValuePoolFilter,
)


class StrategyFrameworkTests(unittest.TestCase):
    def test_value_filter_approves_quality_candidate(self) -> None:
        result = ValuePoolFilter(ValueFilterConfig()).evaluate(
            CandidateProfile(
                "MSFT",
                pe_ratio=25.0,
                forward_pe=22.0,
                peg_ratio=1.4,
                price_to_free_cash_flow=24.0,
                debt_to_equity=0.7,
                revenue_growth_yoy=0.06,
                gross_margin=0.65,
                operating_margin=0.38,
                return_on_invested_capital=0.22,
                free_cash_flow_positive=True,
                average_volume=10_000_000,
            )
        )

        self.assertTrue(result.approved)
        self.assertGreaterEqual(result.score, 60.0)
        self.assertIsNotNone(result.score_breakdown)
        self.assertIn("valuation", result.score_breakdown)

    def test_value_filter_rejects_weak_candidate(self) -> None:
        result = ValuePoolFilter(ValueFilterConfig()).evaluate(
            CandidateProfile(
                "WEAK",
                pe_ratio=80.0,
                free_cash_flow_positive=False,
                average_volume=100_000,
            )
        )

        self.assertFalse(result.approved)
        self.assertIn("pe_ratio above limit", result.reasons)
        self.assertIn("free cash flow is not positive", result.reasons)

    def test_value_filter_scores_undervaluation_quality_demand_and_safety(self) -> None:
        result = ValuePoolFilter(ValueFilterConfig()).evaluate(
            CandidateProfile(
                "VALUE",
                pe_ratio=14.0,
                forward_pe=13.0,
                peg_ratio=0.9,
                price_to_free_cash_flow=12.0,
                debt_to_equity=0.2,
                revenue_growth_yoy=0.12,
                gross_margin=0.55,
                operating_margin=0.22,
                return_on_invested_capital=0.18,
                analyst_revision_positive=True,
                average_volume=12_000_000,
            )
        )

        self.assertTrue(result.approved)
        self.assertGreater(result.score, 80.0)

    def test_moving_average_requires_confirmation_before_entry(self) -> None:
        engine = MovingAverageSignalEngine(
            MovingAverageConfig(short_window=2, long_window=4, confirmation_bars=2)
        )
        now = datetime.now(timezone.utc)
        decisions = [
            engine.update(Bar("AAPL", 1, now, now, price, price, price, price))
            for price in [100.0, 100.1, 100.2, 100.3, 100.5, 100.7]
        ]

        self.assertEqual(decisions[-3].action, "HOLD")
        self.assertEqual(decisions[-2].action, "ENTER_LONG")
        self.assertEqual(decisions[-1].action, "HOLD")
        self.assertEqual(decisions[-1].reason, "entry signal already emitted for this trend")

    def test_tactical_strategy_blocks_stale_quote(self) -> None:
        signal = MovingAverageSignalEngine(
            MovingAverageConfig(short_window=2, long_window=4, confirmation_bars=1)
        )
        now = datetime.now(timezone.utc)
        decision = None
        for price in [100.0, 100.1, 100.2, 100.4]:
            decision = signal.update(Bar("AAPL", 1, now, now, price, price, price, price))
        self.assertIsNotNone(decision)

        strategy = TacticalLongStrategy(["AAPL"], TacticalRiskConfig(max_quote_age_ms=10.0))
        quote = Quote(
            symbol="AAPL",
            last=100.5,
            bid=100.49,
            ask=100.51,
            timestamp=now - timedelta(seconds=5),
            source="test",
        )
        plan = strategy.plan_entry(decision, quote)

        self.assertFalse(plan.approved)
        self.assertEqual(plan.reason, "quote is stale")

    def test_tactical_strategy_creates_bracket_style_plan(self) -> None:
        signal = MovingAverageSignalEngine(
            MovingAverageConfig(short_window=2, long_window=4, confirmation_bars=1)
        )
        now = datetime.now(timezone.utc)
        decision = None
        for price in [100.0, 100.1, 100.2, 100.4]:
            decision = signal.update(Bar("MSFT", 1, now, now, price, price, price, price))
        self.assertIsNotNone(decision)

        strategy = TacticalLongStrategy(
            ["MSFT"],
            TacticalRiskConfig(
                max_quote_age_ms=1000.0,
                profit_target_pct=0.01,
                stop_loss_pct=0.005,
            ),
        )
        quote = Quote(
            symbol="MSFT",
            last=100.5,
            bid=100.49,
            ask=100.51,
            timestamp=now,
            source="test",
        )
        plan = strategy.plan_entry(decision, quote)

        self.assertTrue(plan.approved)
        self.assertIsNotNone(plan.proposal)
        self.assertEqual(plan.proposal.symbol, "MSFT")
        self.assertEqual(plan.proposal.limit_price, 100.51)
        self.assertAlmostEqual(plan.stop_loss_price, 100.0075)
        self.assertAlmostEqual(plan.profit_target_price, 101.5151)

    def test_quote_cache_tracks_freshness(self) -> None:
        cache = InMemoryQuoteCache()
        cache.update(
            Quote(
                symbol="AAPL",
                last=100.0,
                timestamp=datetime.now(timezone.utc),
                source="test",
            )
        )

        self.assertTrue(cache.is_fresh("AAPL", 1000.0))

    def test_ring_buffer_keeps_only_recent_values(self) -> None:
        buffer: RingBuffer[int] = RingBuffer(3)

        for value in [1, 2, 3, 4, 5]:
            buffer.append(value)

        self.assertEqual(buffer.values(), [3, 4, 5])
        self.assertEqual(buffer.latest(), 5)

    def test_rotating_symbol_pool_cycles_fixed_size_batches(self) -> None:
        pool = RotatingSymbolPool(["aapl", "msft", "qqq", "spy"], batch_size=2)

        self.assertEqual(pool.next_batch(), ["AAPL", "MSFT"])
        self.assertEqual(pool.next_batch(), ["QQQ", "SPY"])
        self.assertEqual(pool.next_batch(), ["AAPL", "MSFT"])

    def test_rotating_strategy_scanner_updates_cache_and_bar_ring(self) -> None:
        source = SimulatedQuoteSource(
            {
                "AAPL": [100.0, 100.1, 100.2],
                "MSFT": [200.0, 200.1, 200.2],
                "QQQ": [500.0, 500.1, 500.2],
            }
        )
        scanner = RotatingStrategyScanner(
            source=source,
            symbols=["AAPL", "MSFT", "QQQ"],
            allowed_symbols=["AAPL", "MSFT"],
            config=StrategyScannerConfig(
                batch_size=2,
                interval_seconds=1,
                bar_history_capacity=2,
                moving_average=MovingAverageConfig(
                    short_window=1,
                    long_window=2,
                    confirmation_bars=1,
                ),
                tactical_risk=TacticalRiskConfig(max_quote_age_ms=5000.0),
            ),
        )

        first = scanner.scan_once()
        second = scanner.scan_once()

        self.assertEqual(first["requested_symbols"], ["AAPL", "MSFT"])
        self.assertEqual(second["requested_symbols"], ["QQQ", "AAPL"])
        self.assertEqual(scanner.cache.snapshot().keys(), {"AAPL", "MSFT", "QQQ"})
        self.assertGreaterEqual(second["bar_history_lengths"]["AAPL"], 1)
        self.assertLessEqual(second["bar_history_lengths"]["AAPL"], 2)
        self.assertTrue(second["events"])

    def test_yahoo_chart_payload_builds_latest_quote(self) -> None:
        payload = {
            "chart": {
                "result": [
                    {
                        "timestamp": [1000, 1060, 1120],
                        "indicators": {
                            "quote": [
                                {
                                    "close": [101.0, None, 102.5],
                                    "volume": [10, 0, 30],
                                }
                            ]
                        },
                    }
                ]
            }
        }
        quote = YahooDelayedQuoteSource._quote_from_chart_payload("AAPL", payload)

        self.assertIsNotNone(quote)
        self.assertEqual(quote.symbol, "AAPL")
        self.assertEqual(quote.last, 102.5)
        self.assertEqual(quote.source, "yahoo_delayed")
        self.assertEqual(quote.volume, 30)

        quotes = YahooDelayedQuoteSource._quotes_from_chart_payload(
            "AAPL",
            payload,
            source="yahoo_replay",
        )

        self.assertEqual([item.last for item in quotes], [101.0, 102.5])
        self.assertEqual(quotes[0].source, "yahoo_replay")


if __name__ == "__main__":
    unittest.main()
