import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from trading.config import PROJECT_ROOT, Settings
from trading.market_data import Quote
from trading.models import TradeProposal
from trading.order_rejections import rejection_result
from trading.service import TradingService
from trading.session_calendar import SessionSnapshot, TradingSession, classify_trading_session
from trading.session_policy import SessionOrderContext, policy_for_session, validate_session_order
from trading.strategy import RotatingStrategyScanner


class Scanner(Protocol):
    def scan_once(self) -> Mapping[str, Any]:
        raise NotImplementedError


HealthProvider = Callable[[], Mapping[str, Any]]
OpenOrdersProvider = Callable[[], Sequence[Mapping[str, Any]]]
Submitter = Callable[[TradeProposal], Mapping[str, Any]]


@dataclass(frozen=True)
class AutonomousRuntimeConfig:
    paper_only: bool = True
    kill_switch: bool = False
    cycle_sleep_seconds: float = 30.0
    max_cycles: int = 0
    status_path: Path = PROJECT_ROOT / "reports" / "autonomous_runtime_status.json"
    events_path: Path = PROJECT_ROOT / "reports" / "autonomous_runtime_events.jsonl"

    @classmethod
    def from_env(cls) -> "AutonomousRuntimeConfig":
        return cls(
            paper_only=_bool_env("AUTONOMOUS_PAPER_ONLY", True),
            kill_switch=_bool_env("AUTONOMOUS_KILL_SWITCH", False),
            cycle_sleep_seconds=float(os.getenv("AUTONOMOUS_CYCLE_SLEEP_SECONDS", "30")),
            max_cycles=int(os.getenv("AUTONOMOUS_MAX_CYCLES", "0")),
            status_path=Path(os.getenv("AUTONOMOUS_STATUS_PATH", str(PROJECT_ROOT / "reports" / "autonomous_runtime_status.json"))),
            events_path=Path(os.getenv("AUTONOMOUS_EVENTS_PATH", str(PROJECT_ROOT / "reports" / "autonomous_runtime_events.jsonl"))),
        )


@dataclass(frozen=True)
class RuntimeCycleReport:
    source: str
    created_at: str
    state: str
    session: str
    reason: str
    health_status: str
    requested_symbols: list[str] = field(default_factory=list)
    returned_symbols: list[str] = field(default_factory=list)
    submitted_count: int = 0
    blocked_count: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)


class AutonomousPaperRuntime:
    def __init__(
        self,
        *,
        scanner: Scanner,
        config: AutonomousRuntimeConfig,
        health_provider: HealthProvider,
        open_orders_provider: OpenOrdersProvider,
        submitter: Submitter,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._scanner = scanner
        self._config = config
        self._health_provider = health_provider
        self._open_orders_provider = open_orders_provider
        self._submitter = submitter
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._orders_submitted_this_session = 0
        self._orders_submitted_by_symbol: dict[str, int] = {}
        self._active_session: TradingSession | None = None

    def run_once(self) -> RuntimeCycleReport:
        session_snapshot = classify_trading_session(self._clock())
        if self._active_session != session_snapshot.session:
            self._active_session = session_snapshot.session
            self._orders_submitted_this_session = 0
            self._orders_submitted_by_symbol = {}
        report = self._cycle(session_snapshot)
        self._write_status(report)
        self._append_events(report)
        return report

    def run_forever(self) -> RuntimeCycleReport:
        last_report: RuntimeCycleReport | None = None
        cycles = 0
        while self._config.max_cycles <= 0 or cycles < self._config.max_cycles:
            last_report = self.run_once()
            cycles += 1
            if self._config.max_cycles <= 0 or cycles < self._config.max_cycles:
                time.sleep(self._config.cycle_sleep_seconds)
        if last_report is None:
            raise RuntimeError("runtime did not execute any cycle")
        return last_report

    def _cycle(self, session_snapshot: SessionSnapshot) -> RuntimeCycleReport:
        if not self._config.paper_only:
            return _report(session_snapshot, state="KILL_SWITCH", reason="live trading is disabled by runtime")
        if self._config.kill_switch:
            return _report(session_snapshot, state="KILL_SWITCH", reason="autonomous kill switch is enabled")

        health = self._health_provider()
        health_status = str(health.get("status", "missing"))
        if not _health_ready(health):
            return _report(
                session_snapshot,
                state="PAUSED",
                reason="Trading API or TWS health is not ready",
                health_status=health_status,
            )
        if session_snapshot.session == TradingSession.OFFLINE:
            return _report(session_snapshot, state="OFFLINE", reason=session_snapshot.reason, health_status=health_status)

        policy = policy_for_session(session_snapshot.session)
        if not policy.auto_trade_enabled:
            return _report(session_snapshot, state="PAUSED", reason="session policy disabled paper trading", health_status=health_status)

        open_orders = list(self._open_orders_provider())
        scan = self._scanner.scan_once()
        events = []
        submitted_count = 0
        blocked_count = 0
        for event in scan.get("events", []):
            normalized = dict(event)
            proposal = _proposal_from_event(normalized)
            quote = _quote_from_event(normalized)
            if proposal is None or quote is None:
                normalized["runtime_action"] = "no_proposal"
                events.append(normalized)
                continue
            decision = validate_session_order(
                proposal,
                policy,
                SessionOrderContext(
                    quote=quote,
                    open_orders=open_orders,
                    orders_submitted_this_session=self._orders_submitted_this_session,
                    orders_submitted_by_symbol=self._orders_submitted_by_symbol,
                    strategy_name=str(normalized.get("strategy_name", "tactical_long")),
                ),
            )
            normalized["session_policy_approved"] = decision.approved
            normalized["session_policy_reason"] = decision.reason
            if not decision.approved:
                normalized["runtime_action"] = "blocked"
                blocked_count += 1
                events.append(normalized)
                continue
            result = dict(self._submitter(proposal))
            normalized["runtime_action"] = "submitted" if result.get("approved") is True else "submit_rejected"
            normalized["submission_result"] = result
            submitted_count += 1 if result.get("approved") is True else 0
            self._orders_submitted_this_session += 1 if result.get("approved") is True else 0
            if result.get("approved") is True:
                self._orders_submitted_by_symbol[proposal.symbol] = self._orders_submitted_by_symbol.get(proposal.symbol, 0) + 1
            events.append(normalized)

        return RuntimeCycleReport(
            source="autonomous_paper_runtime",
            created_at=datetime.now(timezone.utc).isoformat(),
            state=session_snapshot.session.value,
            session=session_snapshot.session.value,
            reason=session_snapshot.reason,
            health_status=health_status,
            requested_symbols=list(scan.get("requested_symbols", [])),
            returned_symbols=list(scan.get("returned_symbols", [])),
            submitted_count=submitted_count,
            blocked_count=blocked_count,
            events=events,
        )

    def _write_status(self, report: RuntimeCycleReport) -> None:
        self._config.status_path.parent.mkdir(parents=True, exist_ok=True)
        self._config.status_path.write_text(json.dumps(asdict(report), indent=2, sort_keys=True), encoding="utf-8")

    def _append_events(self, report: RuntimeCycleReport) -> None:
        self._config.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self._config.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(report), sort_keys=True) + "\n")


def build_runtime(
    *,
    scanner: RotatingStrategyScanner,
    settings: Settings,
    config: AutonomousRuntimeConfig,
) -> AutonomousPaperRuntime:
    service = TradingService(settings)

    def submitter(proposal: TradeProposal) -> Mapping[str, Any]:
        payload = {
            "symbol": proposal.symbol,
            "side": proposal.side,
            "quantity": proposal.quantity,
            "limit_price": proposal.limit_price,
            "stop_price": proposal.stop_price,
            "idempotency_key": proposal.idempotency_key,
            "source": "autonomous_paper_runtime",
            "trade_session_token": settings.trade_session_token,
        }
        try:
            return service.submit(payload, transmit=True)
        except Exception as exc:
            return rejection_result(proposal=proposal, error=exc)

    return AutonomousPaperRuntime(
        scanner=scanner,
        config=config,
        health_provider=service.health,
        open_orders_provider=lambda: _read_open_orders(settings),
        submitter=submitter,
    )


def _read_open_orders(settings: Settings) -> Sequence[Mapping[str, Any]]:
    from scripts.list_tws_orders import read_tws_orders

    snapshot = read_tws_orders(
        host=settings.tws_host,
        port=settings.tws_port,
        client_id=settings.tws_client_id + 800,
        timeout=settings.tws_status_timeout,
    )
    orders = snapshot.get("open_orders", [])
    return orders if isinstance(orders, list) else []


def _report(
    session_snapshot: SessionSnapshot,
    *,
    state: str,
    reason: str,
    health_status: str = "not_checked",
) -> RuntimeCycleReport:
    return RuntimeCycleReport(
        source="autonomous_paper_runtime",
        created_at=datetime.now(timezone.utc).isoformat(),
        state=state,
        session=session_snapshot.session.value,
        reason=reason,
        health_status=health_status,
    )


def _health_ready(health: Mapping[str, Any]) -> bool:
    tws = health.get("tws", {})
    return (
        health.get("status") == "ok"
        and health.get("mode") == "PAPER"
        and health.get("lock_state") == "TRADE_LOCK"
        and health.get("paper_transmit_enabled") is True
        and health.get("kill_switch_enabled") is False
        and isinstance(tws, Mapping)
        and tws.get("ready_for_orders") is True
    )


def _proposal_from_event(event: Mapping[str, Any]) -> TradeProposal | None:
    proposal = event.get("proposal")
    if not isinstance(proposal, Mapping):
        return None
    stop_price = proposal.get("stop_price")
    if stop_price is None:
        return None
    return TradeProposal(
        symbol=str(proposal["symbol"]).upper(),
        side=str(proposal["side"]).upper(),
        quantity=int(proposal["quantity"]),
        limit_price=float(proposal["limit_price"]),
        stop_price=float(stop_price),
        idempotency_key=str(proposal["idempotency_key"]),
    )


def _quote_from_event(event: Mapping[str, Any]) -> Quote | None:
    symbol = event.get("symbol")
    price = event.get("price")
    if symbol is None or price is None:
        return None
    return Quote(
        symbol=str(symbol),
        last=float(price),
        bid=_float_or_none(event.get("bid")),
        ask=_float_or_none(event.get("ask")),
        timestamp=datetime.now(timezone.utc),
        source=str(event.get("quote_source", "runtime_event")),
        volume=None,
    )


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
