import unittest

from trading.models import TradeProposal
from trading.risk import RiskEngine, RiskLimits


class RiskEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.proposal = TradeProposal("AAPL", "BUY", 5, 190.0, 185.0)
        self.limits = RiskLimits(
            trading_enabled=True,
            allowed_symbols=frozenset({"AAPL"}),
            max_quantity=20,
            max_order_value=2_000.0,
            max_risk_per_order=100.0,
        )

    def test_disarmed_engine_rejects_every_order(self) -> None:
        limits = RiskLimits(
            trading_enabled=False,
            allowed_symbols=self.limits.allowed_symbols,
            max_quantity=self.limits.max_quantity,
            max_order_value=self.limits.max_order_value,
            max_risk_per_order=self.limits.max_risk_per_order,
        )

        decision = RiskEngine(limits).validate(self.proposal)

        self.assertFalse(decision.approved)
        self.assertEqual(decision.reason, "Trading is DISARMED")

    def test_valid_paper_proposal_is_approved_when_armed(self) -> None:
        decision = RiskEngine(self.limits).validate(self.proposal)

        self.assertTrue(decision.approved)

    def test_order_over_value_limit_is_rejected(self) -> None:
        proposal = TradeProposal("AAPL", "BUY", 20, 190.0, 185.0)

        decision = RiskEngine(self.limits).validate(proposal)

        self.assertFalse(decision.approved)
        self.assertIn("value", decision.reason)

    def test_order_over_quantity_limit_is_rejected(self) -> None:
        limits = RiskLimits(
            trading_enabled=True,
            allowed_symbols=frozenset({"AAPL"}),
            max_quantity=1,
            max_order_value=2_000.0,
            max_risk_per_order=100.0,
        )

        decision = RiskEngine(limits).validate(self.proposal)

        self.assertFalse(decision.approved)
        self.assertIn("Quantity", decision.reason)


if __name__ == "__main__":
    unittest.main()
