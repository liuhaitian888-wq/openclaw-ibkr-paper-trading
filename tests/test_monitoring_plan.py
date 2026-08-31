import unittest

from trading.monitoring_plan import build_monitoring_plan


class MonitoringPlanTests(unittest.TestCase):
    def test_partial_capacity_is_explicitly_rotating_not_all_symbol_streaming(self) -> None:
        plan = build_monitoring_plan(["AAPL", "MSFT", "NVDA", "SPY"], concurrent_limit=2)

        self.assertEqual(plan.mode, "ROTATING_BATCHES")
        self.assertEqual(plan.concurrent_symbols, ("AAPL", "MSFT"))
        self.assertEqual(plan.deferred_symbols, ("NVDA", "SPY"))
        self.assertEqual(plan.refresh_cycles_needed, 2)
        self.assertFalse(plan.strategy_input_enabled)

    def test_full_capacity_is_simultaneous(self) -> None:
        plan = build_monitoring_plan(["AAPL", "MSFT"], concurrent_limit=2)

        self.assertEqual(plan.mode, "SIMULTANEOUS")
        self.assertFalse(plan.deferred_symbols)
