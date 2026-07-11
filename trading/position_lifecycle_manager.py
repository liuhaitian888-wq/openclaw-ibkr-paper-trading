"""Position lifecycle manager for simulation, paper, and live-forbidden modes."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from trading.audit_writer import AuditWriter
from trading.config import PROJECT_ROOT


REPORT_DIR = PROJECT_ROOT / "reports" / "position_lifecycle"
LIFECYCLE_STATES = {
    "CANDIDATE",
    "BUY_SIGNAL_CREATED",
    "BUY_INTENT_CREATED",
    "BUY_SIMULATED_ORDER_CREATED",
    "BUY_SIMULATED_FILLED",
    "BUY_IBKR_PAPER_ORDER_CREATED",
    "BUY_IBKR_PAPER_FILLED",
    "POSITION_OPEN",
    "PROTECTION_REQUIRED",
    "PROTECTION_PENDING",
    "PROTECTION_INTENT_CREATED",
    "PROTECTED",
    "PROFIT_MANAGEMENT",
    "RISK_MANAGEMENT",
    "SELL_SIGNAL_CREATED",
    "SELL_INTENT_CREATED",
    "SELL_SIMULATED_FILLED",
    "SELL_IBKR_PAPER_FILLED",
    "POSITION_CLOSED",
}


@dataclass(frozen=True)
class PositionLifecycle:
    lifecycle_id: str
    symbol: str
    account_id: str
    mode: str
    current_state: str
    candidate_id: str = ""
    signal_id: str = ""
    buy_intent_id: str = ""
    buy_order_id: str = ""
    position_id: str = ""
    protection_required: bool = False
    protection_plan_status: str = ""
    protection_intent_id: str = ""
    sell_intent_id: str = ""
    pnl_ref: str = ""
    created_at: str = ""
    updated_at: str = ""
    blocked_reason: str = ""


class PositionLifecycleManager:
    def __init__(self, audit_writer: AuditWriter | None = None) -> None:
        self.audit_writer = audit_writer or AuditWriter()
        self._states: dict[str, PositionLifecycle] = {}

    def transition(
        self,
        *,
        symbol: str,
        to_state: str,
        mode: str = "SIMULATION",
        account_id: str = "LOCAL_SIMULATION",
        intent_id: str = "",
        order_id: str = "",
        pnl_ref: str = "reports/simulation_pnl/latest.json",
        blocked_reason: str = "",
    ) -> PositionLifecycle:
        if to_state not in LIFECYCLE_STATES:
            raise ValueError(f"unsupported lifecycle state: {to_state}")
        now = datetime.now(timezone.utc).isoformat()
        lifecycle_id = f"{account_id}:{symbol}"
        previous = self._states.get(lifecycle_id)
        state = PositionLifecycle(
            lifecycle_id=lifecycle_id,
            symbol=symbol,
            account_id=account_id,
            mode=mode,
            current_state=to_state,
            buy_intent_id=intent_id if to_state.startswith("BUY") or to_state in {"POSITION_OPEN", "PROTECTION_REQUIRED", "PROTECTION_PENDING"} else (previous.buy_intent_id if previous else ""),
            buy_order_id=order_id if "BUY" in to_state else (previous.buy_order_id if previous else ""),
            position_id=f"{account_id}:{symbol}:position",
            protection_required=to_state in {"PROTECTION_REQUIRED", "PROTECTION_PENDING"},
            protection_plan_status="PENDING" if to_state in {"PROTECTION_REQUIRED", "PROTECTION_PENDING"} else (previous.protection_plan_status if previous else ""),
            protection_intent_id=previous.protection_intent_id if previous else "",
            sell_intent_id=intent_id if to_state.startswith("SELL") else (previous.sell_intent_id if previous else ""),
            pnl_ref=pnl_ref,
            created_at=previous.created_at if previous else now,
            updated_at=now,
            blocked_reason=blocked_reason,
        )
        self._states[lifecycle_id] = state
        self._archive_transition(previous, state, intent_id=intent_id, order_id=order_id)
        return state

    def write_report(self) -> dict[str, Any]:
        self.audit_writer.flush()
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "position_lifecycle_manager",
            "lifecycle_exists": True,
            "states": [asdict(state) for state in self._states.values()],
        }
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        (REPORT_DIR / "latest.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        (REPORT_DIR / "latest.md").write_text(
            f"# Position Lifecycle\n\n- lifecycle_exists: True\n- state_count: {len(self._states)}\n",
            encoding="utf-8",
        )
        return payload

    def _archive_transition(self, previous: PositionLifecycle | None, state: PositionLifecycle, *, intent_id: str, order_id: str) -> None:
        payload = asdict(state)
        event = {
            "event_id": f"{state.lifecycle_id}:{state.current_state}:{state.updated_at}",
            "timestamp_utc": state.updated_at,
            "lifecycle_id": state.lifecycle_id,
            "symbol": state.symbol,
            "account_id": state.account_id,
            "mode": state.mode,
            "from_state": previous.current_state if previous else "",
            "to_state": state.current_state,
            "intent_id": intent_id,
            "order_id": order_id,
            "pnl_ref": state.pnl_ref,
            "blocked_reason": state.blocked_reason,
            "payload_json": json.dumps(payload, sort_keys=True),
        }
        self.audit_writer.submit("position_lifecycle_events", event)
        self.audit_writer.submit("position_lifecycle_state", {**payload, "protection_required": int(state.protection_required), "payload_json": json.dumps(payload, sort_keys=True)})
