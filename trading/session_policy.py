import os
from dataclasses import dataclass
from typing import Mapping, Sequence

from trading.market_data import Quote
from trading.models import TradeProposal
from trading.session_calendar import TradingSession


@dataclass(frozen=True)
class SessionRiskPolicy:
    session: TradingSession
    auto_trade_enabled: bool
    allow_new_entries: bool
    allow_exits: bool
    allow_cancel_replace: bool
    allow_market_orders: bool
    require_limit_entry: bool
    require_protective_stop: bool
    outside_rth: bool
    max_spread_bps: float
    max_order_value: float
    max_open_orders: int
    max_orders_per_session: int
    max_orders_per_symbol: int
    max_position_per_symbol: int
    min_quote_volume: int
    max_quote_age_ms: float
    allowed_strategies: tuple[str, ...]
    blocked_strategies: tuple[str, ...] = ()


@dataclass(frozen=True)
class SessionOrderContext:
    quote: Quote
    open_orders: Sequence[Mapping[str, object]]
    orders_submitted_this_session: int = 0
    orders_submitted_by_symbol: Mapping[str, int] | None = None
    current_position: int = 0
    strategy_name: str = "tactical_long"


@dataclass(frozen=True)
class PolicyDecision:
    approved: bool
    reason: str


def default_session_policies() -> dict[TradingSession, SessionRiskPolicy]:
    return {
        TradingSession.OFFLINE: SessionRiskPolicy(
            TradingSession.OFFLINE,
            False,
            False,
            True,
            True,
            False,
            True,
            True,
            False,
            0.0,
            0.0,
            0,
            0,
            0,
            0,
            0,
            0.0,
            (),
        ),
        TradingSession.OVERNIGHT_PAPER: _policy(
            TradingSession.OVERNIGHT_PAPER,
            outside_rth=True,
            max_spread_bps=8.0,
            max_order_value=250.0,
            max_open_orders=3,
            max_orders_per_session=8,
            max_orders_per_symbol=2,
            max_quote_age_ms=10_000.0,
        ),
        TradingSession.PREMARKET_PAPER: _policy(
            TradingSession.PREMARKET_PAPER,
            outside_rth=True,
            max_spread_bps=12.0,
            max_order_value=300.0,
            max_open_orders=4,
            max_orders_per_session=12,
            max_orders_per_symbol=2,
            max_quote_age_ms=8_000.0,
        ),
        TradingSession.REGULAR_PAPER: _policy(
            TradingSession.REGULAR_PAPER,
            outside_rth=False,
            max_spread_bps=25.0,
            max_order_value=400.0,
            max_open_orders=5,
            max_orders_per_session=20,
            max_orders_per_symbol=3,
            max_quote_age_ms=5_000.0,
        ),
        TradingSession.AFTERHOURS_PAPER: _policy(
            TradingSession.AFTERHOURS_PAPER,
            outside_rth=True,
            max_spread_bps=10.0,
            max_order_value=250.0,
            max_open_orders=3,
            max_orders_per_session=8,
            max_orders_per_symbol=2,
            max_quote_age_ms=10_000.0,
        ),
    }


def policy_for_session(session: TradingSession) -> SessionRiskPolicy:
    policy = default_session_policies()[session]
    return SessionRiskPolicy(
        **{
            **policy.__dict__,
            "max_orders_per_session": _int_env("AUTONOMOUS_MAX_ORDERS_PER_SESSION", policy.max_orders_per_session),
            "max_orders_per_symbol": _int_env("AUTONOMOUS_MAX_ORDERS_PER_SYMBOL", policy.max_orders_per_symbol),
            "max_open_orders": _int_env("AUTONOMOUS_MAX_OPEN_ORDERS", policy.max_open_orders),
            "max_order_value": _float_env("AUTONOMOUS_MAX_ORDER_VALUE", policy.max_order_value),
            "max_position_per_symbol": _int_env("AUTONOMOUS_MAX_POSITION_PER_SYMBOL", policy.max_position_per_symbol),
            "require_protective_stop": _bool_env("AUTONOMOUS_REQUIRE_PROTECTIVE_STOP", policy.require_protective_stop),
            "require_limit_entry": _bool_env("AUTONOMOUS_REQUIRE_LIMIT_ENTRY", policy.require_limit_entry),
        }
    )


def validate_session_order(
    proposal: TradeProposal,
    policy: SessionRiskPolicy,
    context: SessionOrderContext,
) -> PolicyDecision:
    if not policy.auto_trade_enabled:
        return PolicyDecision(False, f"auto trading disabled for {policy.session.value}")
    if proposal.side == "BUY" and not policy.allow_new_entries:
        return PolicyDecision(False, "new entries are disabled for this session")
    if context.strategy_name in policy.blocked_strategies:
        return PolicyDecision(False, "strategy is blocked for this session")
    if policy.allowed_strategies and context.strategy_name not in policy.allowed_strategies:
        return PolicyDecision(False, "strategy is not allowed for this session")
    if policy.require_limit_entry and proposal.limit_price <= 0:
        return PolicyDecision(False, "limit entry is required")
    if policy.require_protective_stop and proposal.stop_price is None:
        return PolicyDecision(False, "protective stop is required")
    if context.quote.age_ms() > policy.max_quote_age_ms:
        return PolicyDecision(False, "quote is stale")
    if context.quote.volume is not None and context.quote.volume < policy.min_quote_volume:
        return PolicyDecision(False, "quote volume is below session minimum")
    spread = context.quote.spread
    if spread is not None and context.quote.last > 0:
        spread_bps = spread / context.quote.last * 10_000.0
        if spread_bps > policy.max_spread_bps:
            return PolicyDecision(False, f"spread {spread_bps:.3f} bps exceeds {policy.max_spread_bps:.3f}")
    if proposal.quantity * proposal.limit_price > policy.max_order_value:
        return PolicyDecision(False, "order value exceeds session maximum")
    if len(context.open_orders) >= policy.max_open_orders:
        return PolicyDecision(False, "max open orders reached")
    if context.orders_submitted_this_session >= policy.max_orders_per_session:
        return PolicyDecision(False, "max orders per session reached")
    by_symbol = context.orders_submitted_by_symbol or {}
    if int(by_symbol.get(proposal.symbol, 0)) >= policy.max_orders_per_symbol:
        return PolicyDecision(False, "max orders per symbol reached")
    if context.current_position + proposal.quantity > policy.max_position_per_symbol:
        return PolicyDecision(False, "max position per symbol reached")
    for order in context.open_orders:
        if (
            str(order.get("symbol", "")).upper() == proposal.symbol
            and str(order.get("action", "")).upper() == proposal.side
            and str(order.get("order_ref", "")) == proposal.idempotency_key
        ):
            return PolicyDecision(False, "duplicate open order already exists")
    return PolicyDecision(True, "session policy approved")


def _policy(
    session: TradingSession,
    *,
    outside_rth: bool,
    max_spread_bps: float,
    max_order_value: float,
    max_open_orders: int,
    max_orders_per_session: int,
    max_orders_per_symbol: int,
    max_quote_age_ms: float,
) -> SessionRiskPolicy:
    return SessionRiskPolicy(
        session=session,
        auto_trade_enabled=True,
        allow_new_entries=True,
        allow_exits=True,
        allow_cancel_replace=True,
        allow_market_orders=False,
        require_limit_entry=True,
        require_protective_stop=True,
        outside_rth=outside_rth,
        max_spread_bps=max_spread_bps,
        max_order_value=max_order_value,
        max_open_orders=max_open_orders,
        max_orders_per_session=max_orders_per_session,
        max_orders_per_symbol=max_orders_per_symbol,
        max_position_per_symbol=5,
        min_quote_volume=0,
        max_quote_age_ms=max_quote_age_ms,
        allowed_strategies=("tactical_long", "dual_moving_average", "grid_rebalance", "zscore_mean_reversion", "lightgbm_style_baseline"),
    )


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    return default if value is None or not value.strip() else int(value)


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    return default if value is None or not value.strip() else float(value)
