from risk.core import OrderRiskConfig


DEFAULT_RISK_CONFIG = OrderRiskConfig(
    allowed_symbols=frozenset({"AAPL", "MSFT", "SPY"}),
    max_order_quantity=1,
    max_order_value=200.0,
    max_gross_exposure=1_200.0,
    min_confidence=0.0,
    live_trading_enabled=False,
    kill_switch_enabled=True,
)
