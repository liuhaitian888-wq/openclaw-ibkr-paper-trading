import unittest

from trading.risk_scaling import scale_risk_limits


class RiskScalingTests(unittest.TestCase):
    def test_limits_scale_proportionally_between_account_balances(self) -> None:
        small = scale_risk_limits(1_000)
        large = scale_risk_limits(10_000)

        self.assertEqual(small.max_order_value, 20.0)
        self.assertEqual(large.max_order_value, 200.0)
        self.assertEqual(small.max_symbol_exposure, 50.0)
        self.assertEqual(large.max_gross_exposure, 2_500.0)

    def test_non_positive_account_equity_is_not_accepted(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive and fresh"):
            scale_risk_limits(0)
