"""BUY decision engine. Emits BUY intents only; never calls IBKR directly."""

from __future__ import annotations

from trading.cycle_snapshot import CycleSnapshot
from trading.order_intents import OrderIntent, make_intent_id, utc_now
from trading.strategy_signals import StrategySignal


def build_buy_intent(signal: StrategySignal, snapshot: CycleSnapshot, *, blocked_reason: str = "") -> OrderIntent:
    return OrderIntent(
        intent_id=make_intent_id(snapshot.cycle_id, signal.symbol, "ENTRY_BUY_LMT", 0),
        timestamp_utc=utc_now(),
        cycle_id=snapshot.cycle_id,
        snapshot_id=snapshot.snapshot_id,
        state_version=snapshot.state_version_max,
        state_version_min=snapshot.state_version_min,
        state_version_max=snapshot.state_version_max,
        symbol=signal.symbol,
        side="BUY",
        intent_type="ENTRY_BUY_LMT",
        order_type="LMT",
        source_signal_id=signal.signal_id,
        source_trigger_id=snapshot.trigger_event_id,
        source_module="buy_decision_engine",
        strategy_source=signal.source_module,
        pool_layer="trade_pool",
        market_session_state="SNAPSHOT",
        spread_ok=True,
        max_order_notional=25.0,
        risk_budget_ok=True,
        protection_plan_required=True,
        protection_plan_status="PENDING",
        execution_allowed=False,
        simulated_order_submitted=False,
        ibkr_paper_order_submitted=False,
        live_order_submitted=False,
        order_submitted=False,
        readback_status="not_submitted",
        blocked_reason=blocked_reason or "intent_only_strategy_signal",
        report_path="reports/buy_sell_strategy_sync/latest.json",
    )


def can_submit_order() -> bool:
    return False


def submit_order(*_args, **_kwargs) -> None:
    raise RuntimeError("BUY engine cannot submit orders directly")
