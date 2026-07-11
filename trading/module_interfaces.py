from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StateFreshness:
    account_summary_age_sec: float | None
    positions_age_sec: float | None
    open_orders_age_sec: float | None
    quotes_age_sec: float | None
    pnl_age_sec: float | None
    protection_coverage_age_sec: float | None


@dataclass(frozen=True)
class QuoteState:
    timestamp: str
    symbol: str
    bid: float | None
    ask: float | None
    last: float | None
    bid_age_sec: float | None
    ask_age_sec: float | None
    last_age_sec: float | None
    spread_pct: float | None
    quote_available: bool
    quote_source: str
    quote_session: str
    quote_use_case: str
    market_data_type: int | None
    market_data_type_name: str
    live_data_confirmed: bool
    delayed_data_detected: bool
    frozen_data_detected: bool
    snapshot_request_used: bool
    regulatory_snapshot_used: bool
    paid_snapshot_risk: bool
    execution_allowed_from_quote: bool
    blocked_reason: str
    threshold_used_sec: float
    actual_age_sec: float | None
    stale_reason: str
    quote_stale: bool
    execution_blocked_due_to_stale_quote: bool


@dataclass(frozen=True)
class PnLState:
    timestamp: str
    account_id: str
    symbol: str | None
    daily_pnl: float | None
    realized_pnl: float | None
    unrealized_pnl: float | None
    pnl_age_sec: float | None
    pnl_subscription_available: bool
    account_level_pnl_available: bool
    symbol_level_pnl_available: bool
    req_pnl_available: bool
    req_pnl_single_available: bool
    fallback_used: bool
    fallback_reason: str


@dataclass(frozen=True)
class ProtectionCoverageState:
    timestamp: str
    symbol: str
    position_qty: float
    existing_stop_qty: float
    uncovered_qty: float
    covered: bool
    overprotected: bool
    duplicate_stop_risk: bool
    protection_coverage_age_sec: float | None


@dataclass(frozen=True)
class OpenOrderState:
    timestamp: str
    symbol: str
    side: str
    order_type: str
    quantity: float
    remaining: float | None
    limit_price: float | None
    stop_price: float | None
    outsideRth_requested: bool | None
    outsideRth_effective: bool | None
    status: str
    ib_order_id: int | None
    open_order_age_sec: float | None


@dataclass(frozen=True)
class PositionState:
    timestamp: str
    symbol: str
    quantity: float
    avg_cost: float | None
    market_price: float | None
    bid: float | None
    ask: float | None
    last: float | None
    market_value: float | None
    unrealized_pnl: float | None
    unrealized_pnl_pct: float | None
    quote_stale: bool
    spread_pct: float | None
    pnl_age_sec: float | None
    position_age_sec: float | None


@dataclass(frozen=True)
class ForceRefreshResult:
    force_refresh_required: bool
    force_refresh_performed: bool
    force_refresh_ok: bool
    positions_refreshed: bool
    open_orders_refreshed: bool
    quotes_refreshed: bool
    pnl_refreshed: bool
    protection_coverage_refreshed: bool
    blocked_reason: str


@dataclass(frozen=True)
class AccountState:
    timestamp: str
    mode: str
    account_id: str
    net_liquidation: float | None
    cash: float | None
    buying_power: float | None
    gross_position_value: float | None
    realized_pnl: float | None
    unrealized_pnl: float | None
    positions: list[PositionState] = field(default_factory=list)
    quotes: list[QuoteState] = field(default_factory=list)
    open_orders: list[OpenOrderState] = field(default_factory=list)
    pnl: list[PnLState] = field(default_factory=list)
    protection_coverage: list[ProtectionCoverageState] = field(default_factory=list)
    freshness: StateFreshness | None = None
    state_stale: bool = True
    blocked_reason: str = ""
    used_cached_state: bool = False
    force_refresh: ForceRefreshResult | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
