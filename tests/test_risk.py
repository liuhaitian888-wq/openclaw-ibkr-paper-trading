import unittest
from dataclasses import replace

from trading.models import TradeProposal
from trading.risk import RiskEngine, RiskLimits


class RiskEngineTests(unittest.TestCase):
    def test_invalid_inputs_never_pass_risk_arithmetic(self):
        engine = RiskEngine(self.limits)
        for field, values in {
            'quantity': [True, 1.5, float('nan'), float('inf')],
            'limit_price': [True, float('nan'), float('inf'), -float('inf')],
            'stop_price': [True, float('nan'), float('inf')],
            'side': ['HOLD'],
        }.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    self.assertFalse(engine.validate(replace(self.proposal, **{field: value})).approved)
        for exposure in [float('nan'), float('inf'), -1, True]:
            with self.subTest(exposure=exposure):
                self.assertFalse(engine.validate(self.proposal, current_gross_exposure=exposure).approved)
        for field in ['max_order_value', 'max_risk_per_order', 'max_symbol_exposure', 'max_gross_exposure']:
            with self.subTest(limit=field):
                self.assertFalse(RiskEngine(replace(self.limits, **{field: float('nan')})).validate(self.proposal).approved)

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

    def test_missing_protective_stop_is_rejected(self) -> None:
        proposal = TradeProposal("AAPL", "BUY", 1, 190.0, None)

        decision = RiskEngine(self.limits).validate(proposal)

        self.assertFalse(decision.approved)
        self.assertIn("Protective stop", decision.reason)

    def test_aggregate_200_boundary_with_existing_pending_exposure(self):
        limits=RiskLimits(trading_enabled=True,allowed_symbols=frozenset({'PFE'}),
            max_quantity=1,max_order_value=200,max_risk_per_order=10,max_gross_exposure=200)
        engine=RiskEngine(limits)
        proposal=TradeProposal('PFE','BUY',1,30,29)
        self.assertTrue(engine.validate(proposal,current_gross_exposure=170).approved)
        self.assertFalse(engine.validate(proposal,current_gross_exposure=170.01).approved)

    def test_symbol_and_gross_exposure_limits_are_not_bypassable(self) -> None:
        symbol_limits = RiskLimits(
            trading_enabled=True,
            allowed_symbols=frozenset({"AAPL"}),
            max_quantity=20,
            max_order_value=2_000.0,
            max_risk_per_order=100.0,
            max_symbol_exposure=1_000.0,
        )
        gross_limits = RiskLimits(
            trading_enabled=True,
            allowed_symbols=frozenset({"AAPL"}),
            max_quantity=20,
            max_order_value=2_000.0,
            max_risk_per_order=100.0,
            max_gross_exposure=800.0,
        )

        symbol = RiskEngine(symbol_limits).validate(self.proposal, current_symbol_exposure=400.0)
        gross = RiskEngine(gross_limits).validate(self.proposal, current_gross_exposure=700.0)

        self.assertIn("Symbol exposure", symbol.reason)
        self.assertIn("Gross exposure", gross.reason)


if __name__ == "__main__":
    unittest.main()
