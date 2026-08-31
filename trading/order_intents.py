"""Unified order intent model for Mode 9 paper automation ledgers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, ClassVar, Mapping


ALLOWED_INTENT_TYPES = {
    "ENTRY_BUY_LMT",
    "ADD_BUY_LMT",
    "PROTECTIVE_SELL_STP_LMT",
    "TAKE_PROFIT_SELL_LMT",
    "TRAILING_STOP_SELL_STP_LMT",
    "GAP_ESCAPE_SELL_LMT",
    "EVENT_RISK_REDUCTION_SELL_LMT",
    "OPTIONS_PROTECTIVE_PUT_PLAN",
    "OPTIONS_COVERED_COLLAR_PLAN",
    "OPTIONS_COVERED_CALL_PLAN",
}


@dataclass(frozen=True)
class OrderIntent:
    intent_id: str
    timestamp_utc: str
    cycle_id: str
    symbol: str
    side: str
    intent_type: str
    order_type: str
    source_module: str
    event_id: str = ""
    snapshot_id: str = ""
    state_version: int = 0
    state_version_min: int = 0
    state_version_max: int = 0
    source_signal_id: str = ""
    source_trigger_id: str = ""
    strategy_source: str = ""
    pool_layer: str = ""
    market_session_state: str = ""
    bid_received: bool = False
    ask_received: bool = False
    quote_ready: bool = False
    spread_ok: bool = False
    position_qty_before: float = 0.0
    position_qty_after_expected: float = 0.0
    max_order_notional: float = 0.0
    risk_budget_ok: bool = False
    protection_plan_required: bool = False
    protection_plan_exists: bool = False
    protection_plan_mode: str = ""
    protection_plan_status: str = ""
    protection_intent_id: str = ""
    protection_due_by: str = ""
    execution_allowed: bool = False
    simulated_order_submitted: bool = False
    ibkr_paper_order_submitted: bool = False
    live_order_submitted: bool = False
    order_submitted: bool = False
    order_id: str = ""
    readback_status: str = "not_submitted"
    blocked_reason: str = ""
    report_path: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    BUY_TYPES: ClassVar[set[str]] = {"ENTRY_BUY_LMT", "ADD_BUY_LMT"}
    SELL_TYPES: ClassVar[set[str]] = {
        "PROTECTIVE_SELL_STP_LMT",
        "TAKE_PROFIT_SELL_LMT",
        "TRAILING_STOP_SELL_STP_LMT",
        "GAP_ESCAPE_SELL_LMT",
        "EVENT_RISK_REDUCTION_SELL_LMT",
    }
    OPTION_PLAN_TYPES: ClassVar[set[str]] = {
        "OPTIONS_PROTECTIVE_PUT_PLAN",
        "OPTIONS_COVERED_COLLAR_PLAN",
        "OPTIONS_COVERED_CALL_PLAN",
    }

    def __post_init__(self) -> None:
        if self.intent_type not in ALLOWED_INTENT_TYPES:
            raise ValueError(f"unsupported intent_type: {self.intent_type}")
        if self.side not in {"BUY", "SELL", "OPTIONS"}:
            raise ValueError(f"unsupported side: {self.side}")
        if self.intent_type in self.BUY_TYPES and self.side != "BUY":
            raise ValueError("BUY intent_type must use side=BUY")
        if self.intent_type in self.SELL_TYPES and self.side != "SELL":
            raise ValueError("SELL intent_type must use side=SELL")
        if self.intent_type in self.OPTION_PLAN_TYPES and self.side != "OPTIONS":
            raise ValueError("options plan intent_type must use side=OPTIONS")
        if self.order_submitted:
            raise ValueError("order_submitted must remain false for intent-only ledger tasks")
        if self.ibkr_paper_order_submitted or self.live_order_submitted:
            raise ValueError("IBKR paper/live submission flags must remain false for intent-only tasks")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["event_id"] = self.event_id or self.intent_id
        return data

    def sqlite_values(self) -> dict[str, Any]:
        return {
            **self.to_dict(),
            "bid_received": int(self.bid_received),
            "ask_received": int(self.ask_received),
            "quote_ready": int(self.quote_ready),
            "spread_ok": int(self.spread_ok),
            "risk_budget_ok": int(self.risk_budget_ok),
            "protection_plan_required": int(self.protection_plan_required),
            "protection_plan_exists": int(self.protection_plan_exists),
            "execution_allowed": int(self.execution_allowed),
            "simulated_order_submitted": int(self.simulated_order_submitted),
            "ibkr_paper_order_submitted": int(self.ibkr_paper_order_submitted),
            "live_order_submitted": int(self.live_order_submitted),
            "order_submitted": int(self.order_submitted),
        }


def make_intent_id(cycle_id: str, symbol: str, intent_type: str, index: int = 0) -> str:
    clean_symbol = (symbol or "NA").lower().replace(" ", "-")
    return f"{cycle_id}-{intent_type.lower()}-{clean_symbol}-{index}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
