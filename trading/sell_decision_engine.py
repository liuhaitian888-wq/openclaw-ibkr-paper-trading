"""SELL decision engine. Emits SELL intents only; never calls IBKR directly."""

from __future__ import annotations

from trading.cycle_snapshot import CycleSnapshot
from trading.order_intents import OrderIntent, make_intent_id, utc_now
from trading.strategy_signals import StrategySignal


SELL_PRIORITY = {
    "GAP_ESCAPE_SELL_LMT": 1,
    "EVENT_RISK_REDUCTION_SELL_LMT": 2,
    "PROTECTIVE_SELL_STP_LMT": 3,
    "TRAILING_STOP_SELL_STP_LMT": 4,
    "TAKE_PROFIT_SELL_LMT": 5,
}


def build_sell_intent(
    signal: StrategySignal,
    snapshot: CycleSnapshot,
    *,
    intent_type: str = "EVENT_RISK_REDUCTION_SELL_LMT",
    position_qty_before: float = 1.0,
    requested_qty: float = 1.0,
    blocked_reason: str = "",
) -> OrderIntent:
    if requested_qty > position_qty_before:
        blocked_reason = "sell_qty_exceeds_position"
        requested_qty = position_qty_before
    return OrderIntent(
        intent_id=make_intent_id(snapshot.cycle_id, signal.symbol, intent_type, 0),
        timestamp_utc=utc_now(),
        cycle_id=snapshot.cycle_id,
        snapshot_id=snapshot.snapshot_id,
        state_version=snapshot.state_version_max,
        state_version_min=snapshot.state_version_min,
        state_version_max=snapshot.state_version_max,
        symbol=signal.symbol,
        side="SELL",
        intent_type=intent_type,
        order_type="LMT" if intent_type != "PROTECTIVE_SELL_STP_LMT" else "STP LMT",
        source_signal_id=signal.signal_id,
        source_trigger_id=snapshot.trigger_event_id,
        source_module="sell_decision_engine",
        strategy_source=signal.source_module,
        market_session_state="SNAPSHOT",
        bid_received=False,
        quote_ready=False,
        spread_ok=True,
        position_qty_before=position_qty_before,
        position_qty_after_expected=max(0.0, position_qty_before - requested_qty),
        risk_budget_ok=True,
        execution_allowed=False,
        simulated_order_submitted=False,
        ibkr_paper_order_submitted=False,
        live_order_submitted=False,
        order_submitted=False,
        readback_status="not_submitted",
        blocked_reason=blocked_reason or "intent_only_strategy_signal",
        report_path="reports/buy_sell_strategy_sync/latest.json",
    )


def priority(intent: OrderIntent) -> int:
    return SELL_PRIORITY.get(intent.intent_type, 99)


def can_submit_order() -> bool:
    return False


def submit_order(*_args, **_kwargs) -> None:
    raise RuntimeError("SELL engine cannot submit orders directly")
