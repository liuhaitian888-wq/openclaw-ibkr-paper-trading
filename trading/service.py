import hmac
import time
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional
from zoneinfo import ZoneInfo

from trading.audit import AuditLog
from trading.config import Settings
from trading.models import TradeProposal
from trading.order_rejections import log_order_rejection
from trading.risk import RiskEngine, RiskLimits
from trading.tws_paper import BrokerSnapshot, OrderConfirmation, TwsPaperBroker
from trading.workflow import attach_workflow_step


class TradingService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._risk = RiskEngine(
            RiskLimits(
                trading_enabled=True,
                allowed_symbols=settings.allowed_symbols,
                max_quantity=settings.max_quantity,
                max_order_value=settings.max_order_value,
                max_risk_per_order=settings.max_risk_per_order,
            )
        )
        self._audit = AuditLog(settings.audit_db)

    def health(self) -> Dict[str, Any]:
        recent_orders = self._audit.list_recent(5)
        tws_status = self._tws_status()
        daily_budget = self._daily_budget_report()
        return {
            "status": "ok",
            "lock_state": self._lock_state(),
            "mode": self.settings.trading_mode,
            "tws_staging_enabled": self.settings.allow_tws_staging,
            "paper_transmit_enabled": self.settings.allow_paper_transmit,
            "outside_rth_enabled": self.settings.allow_outside_rth,
            "kill_switch_enabled": self.settings.trading_kill_switch,
            "trade_session_required": bool(self.settings.trade_session_token),
            "tws": tws_status,
            "limits": {
                "allowed_symbols": sorted(self.settings.allowed_symbols),
                "max_quantity": self.settings.max_quantity,
                "max_order_value": self.settings.max_order_value,
                "max_risk_per_order": self.settings.max_risk_per_order,
                "max_daily_notional_value": self.settings.max_daily_notional_value,
                "daily_notional_timezone": self.settings.daily_notional_timezone,
                "daily_notional_used": (float(daily_budget["entry_budget_used"]) if daily_budget and daily_budget["admission_reconciled"] else (0.0 if daily_budget is None else None)),
                "daily_budget": daily_budget,
            },
            "audit": {
                "database": str(self.settings.audit_db),
                "latest_reconciliation": self._audit.latest_reconciliation(),
                "external_order_block": self._audit.has_unresolved_external_orders(),
                "unresolved_external_orders": self._audit.unresolved_external_orders(),
                "broker_exposure": self._audit.broker_exposure(),
                "recent_order_count": len(recent_orders),
                "recent_orders": [
                    {
                        "idempotency_key": order["idempotency_key"],
                        "created_at": order["created_at"],
                        "mode": order["mode"],
                        "status": order["status"],
                        "symbol": order["proposal"]["symbol"],
                        "side": order["proposal"]["side"],
                        "quantity": order["proposal"]["quantity"],
                    }
                    for order in recent_orders
                ],
            },
        }

    def audit_orders(
        self,
        day: Optional[str] = None,
        timezone_name: str = "Europe/Berlin",
        limit: int = 50,
    ) -> Dict[str, Any]:
        if day:
            orders = self._audit.list_for_date(day, timezone_name)
            return {
                "status": "ok",
                "date": day,
                "timezone": timezone_name,
                "count": len(orders),
                "orders": orders,
            }

        safe_limit = max(1, min(int(limit), 500))
        orders = self._audit.list_recent(safe_limit)
        return {
            "status": "ok",
            "count": len(orders),
            "limit": safe_limit,
            "orders": orders,
        }

    def audit_order(self, idempotency_key: str) -> Dict[str, Any]:
        record = self._audit.get(idempotency_key)
        if record is None:
            raise KeyError("order_not_found")
        record["events"] = self._audit.order_events(idempotency_key)
        return {"status": "ok", "order": record}

    def reconcile_orders(self) -> Dict[str, Any]:
        """Persist broker truth and expose unknown active orders as a hard block."""
        broker = TwsPaperBroker(
            self.settings.tws_host,
            self.settings.tws_port,
            self.settings.tws_client_id,
        )
        snapshot: BrokerSnapshot = broker.collect_snapshot()
        result = self._audit.reconcile(
            list(snapshot.orders),
            list(snapshot.executions),
            list(snapshot.messages),
        )
        result["unresolved_external_orders"] = self._audit.unresolved_external_orders()
        result["workflow_step"] = "broker_reconciliation"
        return result

    def validate(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        try:
            proposal = self._parse_proposal(payload)
        except ValueError as exc:
            raise attach_workflow_step(exc, "service_parse") from exc
        return self._validate_proposal(proposal)

    def validate_limit(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        try:
            proposal = self._parse_proposal(payload, require_stop=False)
        except ValueError as exc:
            raise attach_workflow_step(exc, "service_parse") from exc
        return self._validate_proposal(proposal)

    def _validate_proposal(self, proposal: TradeProposal) -> Dict[str, Any]:
        decision = self._validate_risk(proposal)
        return {
            "status": decision.status,
            "approved": decision.approved,
            "workflow_step": "complete" if decision.approved else "service_risk",
            "reason": decision.reason,
            "mode": self.settings.trading_mode,
            "estimated_value": proposal.quantity * proposal.limit_price,
            "estimated_risk": self._estimated_risk(proposal),
        }

    def submit(self, payload: Mapping[str, Any], transmit: bool) -> Dict[str, Any]:
        total_started = time.perf_counter()
        parse_started = time.perf_counter()
        try:
            proposal = self._parse_proposal(payload)
        except ValueError as exc:
            raise attach_workflow_step(exc, "service_parse") from exc
        timings = {"service_parse_ms": self._elapsed_ms(parse_started)}
        return self._submit_bracket(proposal, payload, transmit, timings, total_started)

    def submit_limit(self, payload: Mapping[str, Any], transmit: bool = True) -> Dict[str, Any]:
        total_started = time.perf_counter()
        parse_started = time.perf_counter()
        try:
            proposal = self._parse_proposal(payload, require_stop=False)
        except ValueError as exc:
            raise attach_workflow_step(exc, "service_parse") from exc
        timings = {"service_parse_ms": self._elapsed_ms(parse_started)}
        return self._submit_limit(proposal, payload, transmit, timings, total_started)

    def _submit_bracket(
        self,
        proposal: TradeProposal,
        payload: Mapping[str, Any],
        transmit: bool,
        timings: Dict[str, Any],
        total_started: float,
    ) -> Dict[str, Any]:
        risk_started = time.perf_counter()
        decision = self._validate_risk(proposal)
        timings["service_risk_ms"] = self._elapsed_ms(risk_started)
        if not decision.approved:
            return self._with_total_timing(
                {
                    "status": "REJECTED",
                    "approved": False,
                    "workflow_step": "service_risk",
                    "reason": decision.reason,
                },
                timings,
                total_started,
            )
        gate_started = time.perf_counter()
        try:
            self._require_submission_allowed(payload, transmit)
        except PermissionError as exc:
            raise attach_workflow_step(exc, "service_gate") from exc
        source = self._parse_source(payload)
        timings["service_gate_ms"] = self._elapsed_ms(gate_started)
        preflight_started = time.perf_counter()
        preflight = self._tws_status()
        timings["service_tws_preflight_ms"] = self._elapsed_ms(preflight_started)
        if not preflight["ready_for_orders"]:
            raise attach_workflow_step(
                PermissionError(f"TWS is not ready for orders: {preflight['error']}"),
                "service_tws_preflight",
            )
        audit_reserve_started = time.perf_counter()
        if not self._audit.reserve(
            proposal,
            "PAPER_TRANSMIT" if transmit else "TWS_STAGE",
            source,
            daily_cap=self.settings.max_daily_notional_value,
            timezone_name=self.settings.daily_notional_timezone,
            admission_check=self._entry_reservation_check(proposal,payload,transmit,linked=True),
        ):
            raise attach_workflow_step(
                ValueError("Duplicate idempotency_key"),
                "service_audit_reserve",
            )
        timings["service_audit_reserve_ms"] = self._elapsed_ms(audit_reserve_started)

        if not self._audit.mark_submission_started(proposal.idempotency_key):
            return self._with_total_timing(dict(status="REJECTED",approved=False,workflow_step="service_transport_admission",
                reason="Another broker submission requires reconciliation; this intent was not sent"),timings,total_started)
        broker = TwsPaperBroker(
            self.settings.tws_host,
            self.settings.tws_port,
            self.settings.tws_client_id,
        )
        try:
            broker_started = time.perf_counter()
            confirmation = broker.submit_bracket(
                proposal,
                transmit=transmit,
                outside_rth=self.settings.allow_outside_rth,
            )
            timings["service_broker_submit_ms"] = self._elapsed_ms(broker_started)
        except Exception as exc:
            self._audit.update(proposal.idempotency_key, "UNKNOWN", str(exc))
            log_order_rejection(proposal=proposal, error=exc)
            raise attach_workflow_step(exc, "service_broker_submit") from exc
        timings.update(confirmation.timings)

        status = self._submission_status(
            confirmation,
            submitted="PAPER_SUBMITTED",
            staged="STAGED_NOT_TRANSMITTED",
            pending_submitted="PAPER_PENDING_CONFIRMATION",
            pending_staged="TWS_STAGE_PENDING_CONFIRMATION",
            transmit=transmit,
        )
        audit_update_started = time.perf_counter()
        self._audit.update(
            proposal.idempotency_key,
            status,
            self._audit_details(confirmation, transmit=transmit, bracket=True),
        )
        native_binding = self._audit.record_submission(
            proposal.idempotency_key,
            list(confirmation.order_ids),
            confirmation.statuses,
            broker_order_evidence=confirmation.broker_order_evidence,
            expected_client_id=self.settings.tws_client_id,
        )
        if native_binding is False:
            status = "PAPER_PENDING_CONFIRMATION"
            self._audit.update(proposal.idempotency_key,status,"Native callback identity incomplete; exact reconciliation required")
        timings["service_audit_update_ms"] = self._elapsed_ms(audit_update_started)
        parent_id, stop_id = confirmation.order_ids
        return self._with_total_timing(
            {
                "status": status,
                "approved": True,
                "workflow_step": "complete",
                "source": source,
                "submitted_at": self._utc_now(),
                "idempotency_key": proposal.idempotency_key,
                "tws_order_ref": proposal.idempotency_key,
                "confirmation_status": "UNVERIFIED_NATIVE_IDENTITY" if native_binding is False else self._confirmation_status(confirmation),
                "native_identity_verified": native_binding,
                "preflight": {
                    "lock_state": self._lock_state(),
                    "tws": preflight,
                },
                "parent_order_id": parent_id,
                "stop_order_id": stop_id,
                "pending_confirmation": confirmation.pending_confirmation or native_binding is False,
                "acknowledged_order_ids": list(confirmation.acknowledged_ids),
                "tws_statuses": confirmation.statuses,
                "tws_open_order_states": confirmation.open_order_states,
                "tws_messages": list(confirmation.messages),
            },
            timings,
            total_started,
        )

    def _submit_limit(
        self,
        proposal: TradeProposal,
        payload: Mapping[str, Any],
        transmit: bool,
        timings: Dict[str, Any],
        total_started: float,
    ) -> Dict[str, Any]:
        risk_started = time.perf_counter()
        decision = self._validate_risk(proposal)
        timings["service_risk_ms"] = self._elapsed_ms(risk_started)
        if not decision.approved:
            return self._with_total_timing(
                {
                    "status": "REJECTED",
                    "approved": False,
                    "workflow_step": "service_risk",
                    "reason": decision.reason,
                },
                timings,
                total_started,
            )
        gate_started = time.perf_counter()
        try:
            self._require_submission_allowed(payload, transmit)
        except PermissionError as exc:
            raise attach_workflow_step(exc, "service_gate") from exc
        source = self._parse_source(payload)
        timings["service_gate_ms"] = self._elapsed_ms(gate_started)
        preflight_started = time.perf_counter()
        preflight = self._tws_status()
        timings["service_tws_preflight_ms"] = self._elapsed_ms(preflight_started)
        if not preflight["ready_for_orders"]:
            raise attach_workflow_step(
                PermissionError(f"TWS is not ready for orders: {preflight['error']}"),
                "service_tws_preflight",
            )
        audit_reserve_started = time.perf_counter()
        if not self._audit.reserve(
            proposal,
            "PAPER_LIMIT_TRANSMIT" if transmit else "LIMIT_STAGE",
            source,
            daily_cap=self.settings.max_daily_notional_value,
            timezone_name=self.settings.daily_notional_timezone,
            admission_check=self._entry_reservation_check(proposal,payload,transmit,linked=False),
        ):
            raise attach_workflow_step(
                ValueError("Duplicate idempotency_key"),
                "service_audit_reserve",
            )
        timings["service_audit_reserve_ms"] = self._elapsed_ms(audit_reserve_started)

        if not self._audit.mark_submission_started(proposal.idempotency_key):
            return self._with_total_timing(dict(status="REJECTED",approved=False,workflow_step="service_transport_admission",
                reason="Another broker submission requires reconciliation; this intent was not sent"),timings,total_started)
        broker = TwsPaperBroker(
            self.settings.tws_host,
            self.settings.tws_port,
            self.settings.tws_client_id,
        )
        try:
            broker_started = time.perf_counter()
            confirmation = broker.submit_limit(
                proposal,
                transmit=transmit,
                outside_rth=self.settings.allow_outside_rth,
            )
            timings["service_broker_submit_ms"] = self._elapsed_ms(broker_started)
        except Exception as exc:
            self._audit.update(proposal.idempotency_key, "UNKNOWN", str(exc))
            log_order_rejection(proposal=proposal, error=exc)
            raise attach_workflow_step(exc, "service_broker_submit") from exc
        timings.update(confirmation.timings)

        status = self._submission_status(
            confirmation,
            submitted="PAPER_LIMIT_SUBMITTED",
            staged="LIMIT_STAGED_NOT_TRANSMITTED",
            pending_submitted="PAPER_LIMIT_PENDING_CONFIRMATION",
            pending_staged="LIMIT_STAGE_PENDING_CONFIRMATION",
            transmit=transmit,
        )
        audit_update_started = time.perf_counter()
        self._audit.update(
            proposal.idempotency_key,
            status,
            self._audit_details(confirmation, transmit=transmit, bracket=False),
        )
        native_binding = self._audit.record_submission(
            proposal.idempotency_key,
            list(confirmation.order_ids),
            confirmation.statuses,
            broker_order_evidence=confirmation.broker_order_evidence,
            expected_client_id=self.settings.tws_client_id,
        )
        if native_binding is False:
            status = "PAPER_LIMIT_PENDING_CONFIRMATION"
            self._audit.update(proposal.idempotency_key,status,"Native callback identity incomplete; exact reconciliation required")
        timings["service_audit_update_ms"] = self._elapsed_ms(audit_update_started)
        (order_id,) = confirmation.order_ids
        return self._with_total_timing(
            {
                "status": status,
                "approved": True,
                "workflow_step": "complete",
                "source": source,
                "submitted_at": self._utc_now(),
                "idempotency_key": proposal.idempotency_key,
                "tws_order_ref": proposal.idempotency_key,
                "confirmation_status": "UNVERIFIED_NATIVE_IDENTITY" if native_binding is False else self._confirmation_status(confirmation),
                "native_identity_verified": native_binding,
                "preflight": {
                    "lock_state": self._lock_state(),
                    "tws": preflight,
                },
                "order_id": order_id,
                "pending_confirmation": confirmation.pending_confirmation or native_binding is False,
                "acknowledged_order_ids": list(confirmation.acknowledged_ids),
                "tws_statuses": confirmation.statuses,
                "tws_open_order_states": confirmation.open_order_states,
                "tws_messages": list(confirmation.messages),
            },
            timings,
            total_started,
        )

    @staticmethod
    def _submission_status(
        confirmation: OrderConfirmation,
        *,
        submitted: str,
        staged: str,
        pending_submitted: str,
        pending_staged: str,
        transmit: bool,
    ) -> str:
        if confirmation.pending_confirmation:
            return pending_submitted if transmit else pending_staged
        return submitted if transmit else staged

    @staticmethod
    def _confirmation_status(confirmation: OrderConfirmation) -> str:
        return "PENDING_CONFIRMATION" if confirmation.pending_confirmation else "CONFIRMED"

    @staticmethod
    def _audit_details(
        confirmation: OrderConfirmation,
        *,
        transmit: bool,
        bracket: bool,
    ) -> str:
        execution_intent = "paper_transmit" if transmit else "stage"
        parts = [
            f"execution_intent={execution_intent}",
            f"transmit={str(transmit).lower()}",
        ]
        if bracket:
            parts.append("bracket_parent_transmit_false_expected=true")
            parts.append(
                "bracket_child_transmit_triggers_bracket="
                + str(transmit).lower()
            )
        parts.append(confirmation.details())
        return ", ".join(parts)

    @classmethod
    def _with_total_timing(
        cls,
        result: Dict[str, Any],
        timings: Dict[str, Any],
        total_started: float,
    ) -> Dict[str, Any]:
        timings["service_total_ms"] = cls._elapsed_ms(total_started)
        result["timings"] = timings
        return result

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 3)

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _lock_state(self) -> str:
        if (
            self.settings.trading_mode == "PAPER"
            and not self.settings.trading_kill_switch
            and self.settings.allow_paper_transmit
            and bool(self.settings.trade_session_token)
        ):
            return "TRADE_LOCK"
        if (
            self.settings.trading_kill_switch
            or self.settings.trading_mode == "DRY_RUN"
            or not self.settings.allow_paper_transmit
        ):
            return "DEV_LOCK"
        return "MIXED"

    def _tws_status(self) -> Dict[str, Any]:
        broker = TwsPaperBroker(
            self.settings.tws_host,
            self.settings.tws_port,
            self.settings.tws_client_id,
        )
        return broker.check_status(self.settings.tws_status_timeout).as_dict()

    def _validate_risk(self, proposal):
        from reporting.telegram_gate import current
        from trading.production_paths import STATE_ROOT
        try:
            from trading.cash_guard import enforce
            enforce(STATE_ROOT,proposal)
            caps=current(STATE_ROOT)['settings']
            if any(caps[k] is not None for k in ('max_symbol_exposure','max_gross_exposure')):
                from trading.portfolio_exposure import measured_exposure
                symbol,gross=measured_exposure(STATE_ROOT,proposal.symbol)
                return self._risk.validate(proposal,current_symbol_exposure=symbol,current_gross_exposure=gross)
            return self._risk.validate(proposal)
        except (OSError,ValueError,TypeError,KeyError,PermissionError) as exc:
            from trading.models import RiskDecision
            return RiskDecision(False,'REJECTED',str(exc))

    def _require_submission_allowed(
        self,
        payload: Mapping[str, Any],
        transmit: bool,
    ) -> None:
        from trading.production_paths import CODE_ROOT, PRODUCTION_WORKSPACE
        if CODE_ROOT == PRODUCTION_WORKSPACE:
            from trading.production_guard import require_module_gate
            require_module_gate("ORDER_SUBMISSION_ALLOWED", duplicate_or_unknown=self._audit.get(str(payload.get("idempotency_key", ""))) is not None)
        if self._audit.has_uncertain_submission():
            raise PermissionError('An existing broker submission is started/unknown; reconcile before new transport')
        if self._audit.has_unresolved_external_orders():
            raise PermissionError(
                "Trading is blocked by an unreconciled external TWS order"
            )
        if self.settings.trading_mode != "PAPER":
            raise PermissionError("TWS order submission requires TRADING_MODE=PAPER")
        if self.settings.trading_kill_switch:
            raise PermissionError("Trading kill switch is enabled")
        if transmit and not self.settings.allow_paper_transmit:
            raise PermissionError("Paper transmission is disabled")
        if transmit:
            self._require_trade_session(payload)
        if not transmit and not self.settings.allow_tws_staging:
            raise PermissionError("TWS staging is disabled")

    def _require_trade_session(self, payload: Mapping[str, Any]) -> None:
        if not self.settings.trade_session_token:
            raise PermissionError("Trade session token is not configured")
        provided = payload.get("trade_session_token")
        if not isinstance(provided, str) or not hmac.compare_digest(
            provided,
            self.settings.trade_session_token,
        ):
            raise PermissionError("Invalid trade session token")

    def _entry_reservation_check(self,proposal,payload,transmit,*,linked):
        from trading.production_paths import STATE_ROOT
        from trading.entry_admission import reserve_cash
        def check(connection,created_at):
            self._require_submission_allowed(payload,transmit)
            decision=self._validate_risk(proposal)
            if not decision.approved:raise PermissionError('Entry risk changed before reservation commit: '+decision.reason)
            if transmit:
                strict=(STATE_ROOT/'runtime/FUNDING_POLICY_REQUIRED').exists() or (STATE_ROOT/'runtime/funding-policy.json').exists()
                if strict and not linked:raise PermissionError('Linked native protective entry required; raw limit-only entry is not authorized by the funded strategy path')
                reserve_cash(connection,STATE_ROOT,proposal,created_at)
        return check

    def _require_daily_notional_available(self, proposal: TradeProposal) -> None:
        cap = self.settings.max_daily_notional_value
        if cap is None:
            return
        current = self._daily_notional_used()
        proposed = proposal.quantity * proposal.limit_price
        if current + proposed > cap:
            raise attach_workflow_step(
                PermissionError(
                    "Daily notional cap exceeded: "
                    f"used={current:.2f}, proposed={proposed:.2f}, cap={cap:.2f}, "
                    f"timezone={self.settings.daily_notional_timezone}"
                ),
                "service_daily_notional",
            )

    def _daily_budget_report(self):
        if self.settings.max_daily_notional_value is None:
            return None
        day=datetime.now(ZoneInfo(self.settings.daily_notional_timezone)).date().isoformat()
        return self._audit.daily_entry_budget_report(day,self.settings.daily_notional_timezone)

    def _daily_notional_used(self) -> float:
        report=self._daily_budget_report()
        if report is None:return 0.0
        if not report['admission_reconciled']:
            raise PermissionError('Daily budget requires native reconciliation')
        return float(report['entry_budget_used'])

    @staticmethod
    def _estimated_risk(proposal: TradeProposal) -> float:
        if proposal.stop_price is None:
            return 0.0
        return proposal.quantity * abs(proposal.limit_price - proposal.stop_price)

    @staticmethod
    def _parse_proposal(
        payload: Mapping[str, Any],
        require_stop: bool = True,
    ) -> TradeProposal:
        required = {
            "symbol",
            "side",
            "quantity",
            "limit_price",
            "idempotency_key",
        }
        if require_stop:
            required.add("stop_price")
        missing = required.difference(payload)
        if missing:
            raise ValueError(f"Missing fields: {', '.join(sorted(missing))}")

        symbol = payload["symbol"]
        side = payload["side"]
        quantity = payload["quantity"]
        limit_price = payload["limit_price"]
        stop_price = payload.get("stop_price")
        idempotency_key = payload["idempotency_key"]
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol must be a non-empty string")
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise ValueError("quantity must be an integer")
        if not isinstance(limit_price, (int, float)) or isinstance(limit_price, bool):
            raise ValueError("limit_price must be numeric")
        if stop_price is not None and (
            not isinstance(stop_price, (int, float)) or isinstance(stop_price, bool)
        ):
            raise ValueError("stop_price must be numeric")
        if not isinstance(idempotency_key, str) or not (8 <= len(idempotency_key) <= 64):
            raise ValueError("idempotency_key must contain 8 to 64 characters")

        return TradeProposal(
            symbol=symbol.strip().upper(),
            side=side,
            quantity=quantity,
            limit_price=float(limit_price),
            stop_price=None if stop_price is None else float(stop_price),
            idempotency_key=idempotency_key,
        )

    @staticmethod
    def _parse_source(payload: Mapping[str, Any]) -> str:
        source = payload.get("source", "unspecified")
        if not isinstance(source, str) or not source.strip():
            return "unspecified"
        return source.strip()[:64]
