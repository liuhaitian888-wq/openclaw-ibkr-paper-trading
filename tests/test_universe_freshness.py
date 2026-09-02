import unittest

from trading.universe_freshness import FreshnessSla, assess_universe_freshness


def row(symbol: str, fresh: bool) -> dict:
    return {"symbol": symbol, "bid_fresh": fresh, "ask_fresh": fresh}


class UniverseFreshnessTests(unittest.TestCase):
    def test_stale_position_enters_safe_mode_even_if_universe_has_fresh_quotes(self) -> None:
        result = assess_universe_freshness(
            universe_symbols=["AAPL", "MSFT"], quote_rows=[row("AAPL", False), row("MSFT", True)],
            held_symbols=["AAPL"], open_order_symbols=[], high_pool_symbols=[], abnormal_symbols=[],
            cycle=1, rotation_state={}, sla=FreshnessSla(min_universe_coverage_ratio=0.5, max_universe_stale_ratio=0.5),
        )

        self.assertTrue(result["safe_mode"])
        self.assertIn("critical_symbol_stale", result["blocked_reason"])

    def test_normal_universe_can_rotate_inside_revisit_window(self) -> None:
        rotation = {"AAPL": 1, "MSFT": 1}
        result = assess_universe_freshness(
            universe_symbols=["AAPL", "MSFT", "NVDA", "AMD"],
            quote_rows=[row("NVDA", True), row("AMD", True)],
            held_symbols=[], open_order_symbols=[], high_pool_symbols=[], abnormal_symbols=[],
            cycle=2, rotation_state=rotation,
            sla=FreshnessSla(min_universe_coverage_ratio=0.5, max_universe_stale_ratio=0.5, normal_revisit_cycles=4),
        )

        self.assertFalse(result["safe_mode"])
        self.assertTrue(result["execution_allowed"])

    def test_low_coverage_is_not_paper_ready(self) -> None:
        result = assess_universe_freshness(
            universe_symbols=["AAPL", "MSFT", "NVDA", "AMD"], quote_rows=[row("AAPL", True)],
            held_symbols=[], open_order_symbols=[], high_pool_symbols=[], abnormal_symbols=[],
            cycle=5, rotation_state={"AAPL": 4},
            sla=FreshnessSla(min_universe_coverage_ratio=0.7, max_universe_stale_ratio=0.3),
        )

        self.assertTrue(result["safe_mode"])
        self.assertIn("universe_coverage_below_sla", result["blocked_reason"])
