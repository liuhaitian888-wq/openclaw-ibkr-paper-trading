"""Canonical six-layer symbol pool state.

This module keeps the six-layer pool logic separate from broker submission.
It records why a symbol moves, but it does not place, cancel, or modify orders.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from trading.paper_audit_db import DB_PATH, ensure_paper_automation_tables, insert_event


LAYERS = (
    "MASTER_UNIVERSE",
    "ELIGIBLE_UNIVERSE",
    "SCAN_POOL",
    "WATCH_POOL",
    "SIGNAL_EXECUTION_READY_POOL",
    "PAPER_EXECUTION_POSITION_POOL",
)
LAYER_INDEX = {layer: index for index, layer in enumerate(LAYERS)}

EXECUTION_STATUSES = {
    "NONE": 0,
    "PROPOSED": 1,
    "APPROVED_FOR_PAPER": 2,
    "SUBMISSION_REQUESTED": 3,
    "SUBMITTED": 4,
    "ACKNOWLEDGED": 5,
    "PARTIALLY_FILLED": 6,
    "FILLED": 7,
    "CANCEL_REQUESTED": 8,
    "CANCELLED": 9,
    "REJECTED": 10,
    "EXPIRED": 11,
    "POSITION_OPEN": 12,
    "EXIT_PLANNED": 13,
    "EXIT_SUBMITTED": 14,
    "POSITION_CLOSED": 15,
}
ACTIVE_ORDER_STATUSES = {"SUBMISSION_REQUESTED", "SUBMITTED", "ACKNOWLEDGED", "PARTIALLY_FILLED", "EXIT_SUBMITTED"}


@dataclass(frozen=True)
class PoolTransition:
    transition_id: str
    symbol: str
    from_layer: str
    to_layer: str
    timestamp_utc: str
    triggering_component: str
    reason_code: str
    explanation: str
    score: float | None = None
    market_data_timestamp: str = ""
    trace_id: str = ""


@dataclass(frozen=True)
class SymbolPoolState:
    symbol: str
    current_layer: str = "MASTER_UNIVERSE"
    enabled: bool = True
    security_type: str = "STK"
    exchange: str = ""
    currency: str = "USD"
    source: str = ""
    time_added: str = ""
    last_update_time: str = ""
    exclusion_reason: str = ""
    contract_resolved: bool = False
    eligibility: dict[str, Any] = field(default_factory=dict)
    market_data_state: dict[str, Any] = field(default_factory=dict)
    strategy_assessments: dict[str, dict[str, Any]] = field(default_factory=dict)
    structured_events: list[dict[str, Any]] = field(default_factory=list)
    risk_state: dict[str, Any] = field(default_factory=dict)
    execution_state: dict[str, Any] = field(default_factory=lambda: {"status": "NONE"})
    position_state: dict[str, Any] = field(default_factory=dict)
    timestamps: dict[str, str] = field(default_factory=dict)
    transition_history: list[PoolTransition] = field(default_factory=list)


class PoolStateManager:
    def __init__(self, *, db_path: Path = DB_PATH, now: str | None = None) -> None:
        self.db_path = db_path
        self._now_override = now
        self._states: dict[str, SymbolPoolState] = {}
        ensure_paper_automation_tables(db_path)

    def upsert_master(
        self,
        *,
        symbol: str,
        security_type: str = "STK",
        exchange: str = "",
        currency: str = "USD",
        source: str = "manual",
        enabled: bool = True,
        exclusion_reason: str = "",
        trace_id: str = "",
    ) -> SymbolPoolState:
        clean = normalize_symbol(symbol)
        now = self.now()
        previous = self._states.get(clean)
        state = replace(
            previous or SymbolPoolState(symbol=clean, time_added=now),
            symbol=clean,
            security_type=security_type,
            exchange=exchange,
            currency=currency,
            source=source,
            enabled=enabled,
            exclusion_reason=exclusion_reason,
            last_update_time=now,
            timestamps={**(previous.timestamps if previous else {}), "master_updated_at": now},
        )
        self._states[clean] = state
        if previous is None:
            state = self._transition(
                state,
                "MASTER_UNIVERSE",
                component="master_universe",
                reason_code="MASTER_ADDED",
                explanation="symbol added to master universe",
                trace_id=trace_id,
                allow_same=True,
            )
        else:
            self._persist_state(state)
        return state

    def evaluate_eligibility(
        self,
        symbol: str,
        *,
        contract_resolved: bool,
        market_data_available: bool = True,
        price: float | None = None,
        average_volume: float | None = None,
        min_price: float = 1.0,
        min_average_volume: float = 1_000_000,
        blocked: bool = False,
        blocked_reason: str = "",
        trace_id: str = "",
    ) -> SymbolPoolState:
        state = self.require_state(symbol)
        failures = []
        if not state.enabled:
            failures.append("SYMBOL_BLOCKED")
        if blocked:
            failures.append(blocked_reason or "SYMBOL_BLOCKED")
        if not contract_resolved:
            failures.append("CONTRACT_NOT_RESOLVED")
        if state.security_type not in {"STK", "ETF"}:
            failures.append("UNSUPPORTED_SECURITY_TYPE")
        if state.currency and state.currency != "USD":
            failures.append("UNSUPPORTED_CURRENCY")
        if not market_data_available:
            failures.append("MARKET_DATA_UNAVAILABLE")
        if price is not None and price < min_price:
            failures.append("PRICE_BELOW_MINIMUM")
        if average_volume is not None and average_volume < min_average_volume:
            failures.append("LOW_LIQUIDITY")
        eligibility = {
            "contract_resolved": contract_resolved,
            "market_data_available": market_data_available,
            "price": price,
            "average_volume": average_volume,
            "eligible": not failures,
            "failed_checks": failures,
        }
        state = replace(state, contract_resolved=contract_resolved, eligibility=eligibility, last_update_time=self.now())
        self._states[state.symbol] = state
        if failures:
            return self._transition(
                state,
                "MASTER_UNIVERSE",
                component="eligibility_gate",
                reason_code=failures[0],
                explanation="symbol failed eligibility checks",
                trace_id=trace_id,
                allow_demote=True,
                allow_same=True,
            )
        return self._transition(
            state,
            "ELIGIBLE_UNIVERSE",
            component="eligibility_gate",
            reason_code="ELIGIBLE",
            explanation="symbol passed hard eligibility checks",
            trace_id=trace_id,
        )

    def nominate_scan(
        self,
        symbol: str,
        *,
        strategy: str,
        score: float,
        reason: str,
        data_timestamp: str = "",
        ttl_seconds: int = 900,
        trace_id: str = "",
    ) -> SymbolPoolState:
        state = self.require_state(symbol)
        expires_at = iso_add(self.now(), ttl_seconds)
        assessments = {
            **state.strategy_assessments,
            strategy: {
                "strategy": strategy,
                "coarse_score": score,
                "nomination_reason": reason,
                "scan_timestamp": self.now(),
                "data_timestamp": data_timestamp,
                "expires_at": expires_at,
            },
        }
        state = replace(state, strategy_assessments=assessments, last_update_time=self.now())
        self._states[state.symbol] = state
        return self._transition(
            state,
            "SCAN_POOL",
            component="scan_pool",
            reason_code="SCAN_NOMINATED",
            explanation=reason,
            score=score,
            market_data_timestamp=data_timestamp,
            trace_id=trace_id,
        )

    def promote_to_watch(
        self,
        symbol: str,
        *,
        strategy: str,
        quote: Mapping[str, Any],
        entry_reason: str,
        score: float,
        max_spread_pct: float = 0.01,
        quote_freshness_sec: float = 5.0,
        ttl_seconds: int = 600,
        trace_id: str = "",
    ) -> SymbolPoolState:
        state = self.require_state(symbol)
        quote_check = quote_readiness(quote, quote_freshness_sec=quote_freshness_sec, max_spread_pct=max_spread_pct, now=self.now())
        market_data = {**state.market_data_state, **dict(quote), **quote_check, "watch_expires_at": iso_add(self.now(), ttl_seconds)}
        state = replace(state, market_data_state=market_data, last_update_time=self.now())
        self._states[state.symbol] = state
        if not quote_check["ready"]:
            return self._transition(
                state,
                "ELIGIBLE_UNIVERSE",
                component="watch_pool",
                reason_code=quote_check["reason_code"],
                explanation=quote_check["explanation"],
                score=score,
                market_data_timestamp=str(quote.get("timestamp") or ""),
                trace_id=trace_id,
                allow_demote=True,
            )
        return self._transition(
            state,
            "WATCH_POOL",
            component="watch_pool",
            reason_code="WATCH_PROMOTED",
            explanation=entry_reason,
            score=score,
            market_data_timestamp=str(quote.get("timestamp") or ""),
            trace_id=trace_id,
        )

    def evaluate_signal(
        self,
        symbol: str,
        *,
        signal: Mapping[str, Any],
        market_session: Mapping[str, Any],
        risk: Mapping[str, Any],
        execution: Mapping[str, Any],
        news_events: Sequence[Mapping[str, Any]] = (),
        max_signal_age_sec: float = 120.0,
        trace_id: str = "",
    ) -> SymbolPoolState:
        state = self.require_state(symbol)
        failures = signal_failures(signal, market_session, risk, execution, news_events, now=self.now(), max_signal_age_sec=max_signal_age_sec)
        state = replace(
            state,
            structured_events=[dict(item) for item in news_events],
            risk_state=dict(risk),
            execution_state={**state.execution_state, **dict(execution), "last_signal": dict(signal)},
            last_update_time=self.now(),
        )
        self._states[state.symbol] = state
        if failures:
            target = "WATCH_POOL" if state.current_layer in {"WATCH_POOL", "SIGNAL_EXECUTION_READY_POOL"} else state.current_layer
            return self._transition(
                state,
                target,
                component="signal_execution_gate",
                reason_code=failures[0],
                explanation="; ".join(failures),
                score=to_float(signal.get("score")),
                market_data_timestamp=str(state.market_data_state.get("timestamp") or ""),
                trace_id=trace_id,
                allow_demote=True,
                allow_same=True,
            )
        return self._transition(
            state,
            "SIGNAL_EXECUTION_READY_POOL",
            component="signal_execution_gate",
            reason_code="SIGNAL_READY",
            explanation="signal passed market-data, session, risk, and paper execution gates",
            score=to_float(signal.get("score")),
            market_data_timestamp=str(state.market_data_state.get("timestamp") or ""),
            trace_id=trace_id,
        )

    def enter_execution_pool(self, symbol: str, *, order_id: str, intent_id: str, trace_id: str = "") -> SymbolPoolState:
        state = self.require_state(symbol)
        if state.execution_state.get("live_trading_enabled") is True:
            return self._transition(
                state,
                "SIGNAL_EXECUTION_READY_POOL",
                component="paper_execution_gate",
                reason_code="LIVE_TRADING_DISABLED",
                explanation="live trading is not allowed",
                trace_id=trace_id,
                allow_same=True,
            )
        if has_active_order(state):
            return self._transition(
                state,
                state.current_layer,
                component="paper_execution_gate",
                reason_code="DUPLICATE_ORDER",
                explanation="active order already exists for symbol",
                trace_id=trace_id,
                allow_same=True,
            )
        execution_state = {
            **state.execution_state,
            "status": "SUBMISSION_REQUESTED",
            "order_id": order_id,
            "intent_id": intent_id,
            "order_submitted": False,
            "paper_only": True,
        }
        state = replace(state, execution_state=execution_state, last_update_time=self.now())
        self._states[state.symbol] = state
        return self._transition(
            state,
            "PAPER_EXECUTION_POSITION_POOL",
            component="paper_execution_gate",
            reason_code="PAPER_SUBMISSION_REQUESTED",
            explanation="paper order submission requested; awaiting IBKR callback",
            trace_id=trace_id,
        )

    def apply_order_callback(
        self,
        symbol: str,
        *,
        callback_status: str,
        filled_quantity: float = 0.0,
        remaining_quantity: float = 0.0,
        order_id: str = "",
        reason: str = "",
        trace_id: str = "",
    ) -> SymbolPoolState:
        state = self.require_state(symbol)
        normalized = normalize_status(callback_status)
        previous = str(state.execution_state.get("status") or "NONE")
        if EXECUTION_STATUSES[normalized] < EXECUTION_STATUSES.get(previous, 0):
            return self._transition(
                state,
                state.current_layer,
                component="ibkr_callback_bridge",
                reason_code="OUT_OF_ORDER_CALLBACK_IGNORED",
                explanation=f"ignored {normalized} after {previous}",
                trace_id=trace_id,
                allow_same=True,
            )
        execution_state = {
            **state.execution_state,
            "status": normalized,
            "order_id": order_id or state.execution_state.get("order_id", ""),
            "filled_quantity": filled_quantity,
            "remaining_quantity": remaining_quantity,
            "last_callback_reason": reason,
            "order_submitted": normalized in {"SUBMITTED", "ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED"},
        }
        position_state = dict(state.position_state)
        if normalized == "PARTIALLY_FILLED":
            position_state.update({"position_status": "PARTIAL", "filled_quantity": filled_quantity, "remaining_quantity": remaining_quantity})
        elif normalized == "FILLED":
            position_state.update({"position_status": "OPEN", "filled_quantity": filled_quantity, "remaining_quantity": 0.0})
        state = replace(state, execution_state=execution_state, position_state=position_state, last_update_time=self.now())
        self._states[state.symbol] = state
        reason_code = f"IBKR_{normalized}"
        return self._transition(
            state,
            state.current_layer,
            component="ibkr_callback_bridge",
            reason_code=reason_code,
            explanation=reason or f"IBKR callback status {normalized}",
            trace_id=trace_id,
            allow_same=True,
        )

    def expire(self, symbol: str, *, component: str, reason_code: str, explanation: str, trace_id: str = "") -> SymbolPoolState:
        state = self.require_state(symbol)
        return self._transition(
            state,
            "ELIGIBLE_UNIVERSE",
            component=component,
            reason_code=reason_code,
            explanation=explanation,
            trace_id=trace_id,
            allow_demote=True,
        )

    def save(self) -> None:
        ensure_paper_automation_tables(self.db_path)
        with sqlite3.connect(self.db_path) as con:
            con.execute("DELETE FROM canonical_pool_state")
            for state in self._states.values():
                payload = state_to_dict(state)
                con.execute(
                    "INSERT INTO canonical_pool_state (symbol, current_layer, updated_at, has_active_order, payload_json) VALUES (?, ?, ?, ?, ?)",
                    (
                        state.symbol,
                        state.current_layer,
                        state.last_update_time,
                        int(has_active_order(state)),
                        json.dumps(payload, sort_keys=True),
                    ),
                )

    def load(self) -> None:
        ensure_paper_automation_tables(self.db_path)
        with sqlite3.connect(self.db_path) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute("SELECT payload_json FROM canonical_pool_state").fetchall()
        self._states = {}
        for row in rows:
            payload = json.loads(row["payload_json"])
            state = state_from_dict(payload)
            if expired_signal(state, now=self.now()) and not has_active_order(state):
                state = replace(state, current_layer="ELIGIBLE_UNIVERSE", execution_state={**state.execution_state, "status": "EXPIRED"})
            self._states[state.symbol] = state

    def get(self, symbol: str) -> SymbolPoolState | None:
        return self._states.get(normalize_symbol(symbol))

    def require_state(self, symbol: str) -> SymbolPoolState:
        state = self.get(symbol)
        if state is None:
            raise KeyError(f"symbol not in master universe: {symbol}")
        return state

    def now(self) -> str:
        return self._now_override or datetime.now(timezone.utc).isoformat()

    def set_now(self, value: str) -> None:
        self._now_override = value

    def _transition(
        self,
        state: SymbolPoolState,
        to_layer: str,
        *,
        component: str,
        reason_code: str,
        explanation: str,
        score: float | None = None,
        market_data_timestamp: str = "",
        trace_id: str = "",
        allow_demote: bool = False,
        allow_same: bool = False,
    ) -> SymbolPoolState:
        if to_layer not in LAYER_INDEX:
            raise ValueError(f"unsupported pool layer: {to_layer}")
        from_layer = state.current_layer
        delta = LAYER_INDEX[to_layer] - LAYER_INDEX[from_layer]
        if delta > 1:
            raise ValueError(f"unexplained pool jump blocked: {from_layer}->{to_layer}")
        if delta < 0 and not allow_demote:
            raise ValueError(f"demotion requires explicit allow_demote: {from_layer}->{to_layer}")
        if delta == 0 and not allow_same:
            return self._persist_state(state)
        now = self.now()
        transition = PoolTransition(
            transition_id=f"{state.symbol}:{from_layer}->{to_layer}:{now}",
            symbol=state.symbol,
            from_layer=from_layer,
            to_layer=to_layer,
            timestamp_utc=now,
            triggering_component=component,
            reason_code=reason_code,
            explanation=explanation,
            score=score,
            market_data_timestamp=market_data_timestamp,
            trace_id=trace_id,
        )
        next_state = replace(
            state,
            current_layer=to_layer,
            last_update_time=now,
            transition_history=[*state.transition_history, transition],
            timestamps={**state.timestamps, "last_transition_at": now},
        )
        self._states[next_state.symbol] = next_state
        self._persist_transition(transition)
        return self._persist_state(next_state)

    def _persist_state(self, state: SymbolPoolState) -> SymbolPoolState:
        self._states[state.symbol] = state
        self.save()
        return state

    def _persist_transition(self, transition: PoolTransition) -> None:
        payload = asdict(transition)
        insert_event(
            "canonical_pool_transition_events",
            {
                "transition_id": transition.transition_id,
                "timestamp_utc": transition.timestamp_utc,
                "symbol": transition.symbol,
                "from_layer": transition.from_layer,
                "to_layer": transition.to_layer,
                "triggering_component": transition.triggering_component,
                "reason_code": transition.reason_code,
                "explanation": transition.explanation,
                "score": transition.score,
                "market_data_timestamp": transition.market_data_timestamp,
                "trace_id": transition.trace_id,
                "payload_json": json.dumps(payload, sort_keys=True),
            },
            db_path=self.db_path,
        )


def quote_readiness(quote: Mapping[str, Any], *, quote_freshness_sec: float, max_spread_pct: float, now: str) -> dict[str, Any]:
    bid = to_float(quote.get("bid"))
    ask = to_float(quote.get("ask"))
    last = to_float(quote.get("last"))
    timestamp = str(quote.get("timestamp") or quote.get("ask_timestamp") or "")
    age = age_seconds(timestamp, now)
    if bid is None or bid <= 0:
        return {"ready": False, "reason_code": "MISSING_BID", "explanation": "bid is missing or invalid", "quote_age_sec": age}
    if ask is None or ask <= 0:
        return {"ready": False, "reason_code": "STALE_ASK" if age is not None and age > quote_freshness_sec else "MISSING_ASK", "explanation": "ask is missing, invalid, or stale", "quote_age_sec": age}
    if age is None or age > quote_freshness_sec:
        return {"ready": False, "reason_code": "STALE_ASK", "explanation": "ask quote is stale", "quote_age_sec": age}
    spread_pct = (ask - bid) / max((ask + bid) / 2, 0.0001)
    if spread_pct > max_spread_pct:
        return {"ready": False, "reason_code": "SPREAD_TOO_WIDE", "explanation": "bid/ask spread exceeds configured limit", "quote_age_sec": age, "spread_pct": spread_pct}
    if last is not None and last <= 0:
        return {"ready": False, "reason_code": "INVALID_LAST", "explanation": "last price is invalid", "quote_age_sec": age, "spread_pct": spread_pct}
    return {"ready": True, "reason_code": "", "explanation": "", "quote_age_sec": age, "spread_pct": spread_pct}


def signal_failures(
    signal: Mapping[str, Any],
    market_session: Mapping[str, Any],
    risk: Mapping[str, Any],
    execution: Mapping[str, Any],
    news_events: Sequence[Mapping[str, Any]],
    *,
    now: str,
    max_signal_age_sec: float,
) -> list[str]:
    failures: list[str] = []
    if not signal.get("valid", False):
        failures.append("SIGNAL_INVALID")
    if age_seconds(str(signal.get("timestamp") or ""), now) is None or age_seconds(str(signal.get("timestamp") or ""), now) > max_signal_age_sec:
        failures.append("SIGNAL_EXPIRED")
    if signal.get("source") == "news" or (news_events and not signal.get("strategy_confirmed", False)):
        failures.append("NEWS_EVENT_CANNOT_AUTHORIZE_TRADE")
    if market_session.get("expected_live_bid_ask") is False:
        failures.append("MARKET_CLOSED")
    if market_session.get("order_type_allowed") is False:
        failures.append("SESSION_NOT_ALLOWED")
    if not risk.get("approved", False):
        failures.append(str(risk.get("reason_code") or "RISK_LIMIT_REACHED"))
    if execution.get("live_trading_enabled") is True:
        failures.append("LIVE_TRADING_DISABLED")
    if not execution.get("paper_account_confirmed", False):
        failures.append("PAPER_ACCOUNT_NOT_CONFIRMED")
    if execution.get("duplicate_order") is True:
        failures.append("DUPLICATE_ORDER")
    if execution.get("contract_resolved") is False:
        failures.append("CONTRACT_NOT_RESOLVED")
    return list(dict.fromkeys(failures))


def expired_signal(state: SymbolPoolState, *, now: str) -> bool:
    signal = state.execution_state.get("last_signal") if isinstance(state.execution_state, Mapping) else None
    if not isinstance(signal, Mapping):
        return False
    return age_seconds(str(signal.get("timestamp") or ""), now) is None or age_seconds(str(signal.get("timestamp") or ""), now) > 120.0


def has_active_order(state: SymbolPoolState) -> bool:
    return str(state.execution_state.get("status") or "NONE") in ACTIVE_ORDER_STATUSES


def normalize_status(value: str) -> str:
    normalized = value.strip().upper().replace(" ", "_")
    aliases = {"PARTIAL": "PARTIALLY_FILLED", "PRESUBMITTED": "SUBMITTED", "APISUBMITTED": "SUBMITTED"}
    normalized = aliases.get(normalized, normalized)
    if normalized not in EXECUTION_STATUSES:
        raise ValueError(f"unsupported execution status: {value}")
    return normalized


def state_to_dict(state: SymbolPoolState) -> dict[str, Any]:
    payload = asdict(state)
    payload["transition_history"] = [asdict(item) if isinstance(item, PoolTransition) else item for item in state.transition_history]
    return payload


def state_from_dict(payload: Mapping[str, Any]) -> SymbolPoolState:
    transitions = [PoolTransition(**item) for item in payload.get("transition_history", [])]
    clean = dict(payload)
    clean["transition_history"] = transitions
    return SymbolPoolState(**clean)


def normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper()


def to_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def age_seconds(timestamp: str, now: str) -> float | None:
    ts = parse_time(timestamp)
    current = parse_time(now)
    if ts is None or current is None:
        return None
    return max(0.0, (current - ts).total_seconds())


def iso_add(timestamp: str, seconds: int) -> str:
    parsed = parse_time(timestamp) or datetime.now(timezone.utc)
    return (parsed + timedelta(seconds=seconds)).isoformat()


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
