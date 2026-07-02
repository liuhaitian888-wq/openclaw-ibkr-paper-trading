from trading.models import TradeProposal
from trading.risk import RiskEngine, RiskLimits


def main() -> None:
    proposal = TradeProposal(
        symbol="AAPL",
        side="BUY",
        quantity=1,
        limit_price=190.00,
        stop_price=185.00,
    )
    engine = RiskEngine(
        RiskLimits(
            trading_enabled=False,
            allowed_symbols=frozenset({"AAPL", "MSFT", "SPY"}),
            max_quantity=1,
            max_order_value=200.00,
            max_risk_per_order=10.00,
        )
    )

    decision = engine.validate(proposal)
    print(f"Decision: {decision.status}")
    print(f"Reason: {decision.reason}")


if __name__ == "__main__":
    main()
