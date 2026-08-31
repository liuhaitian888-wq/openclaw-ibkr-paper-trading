"""US equity market-session classification and reporting.

This module is intentionally independent from quote acquisition.  A missing
bid/ask can be a normal closed-session outcome, so execution readiness should
ask the session layer before retrying market-data subscriptions.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.wrapper import EWrapper


PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = PROJECT_ROOT / "reports" / "market_session"
NY = ZoneInfo("America/New_York")
LOCAL = ZoneInfo(os.getenv("OPENCLAW_LOCAL_TIMEZONE", "Europe/Berlin"))


class MarketSessionState(str, Enum):
    PREMARKET = "PREMARKET"
    REGULAR = "REGULAR"
    AFTERHOURS = "AFTERHOURS"
    CLOSED = "CLOSED"
    WEEKEND = "WEEKEND"
    HOLIDAY = "HOLIDAY"
    EARLY_CLOSE = "EARLY_CLOSE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class MarketSessionConfig:
    exchange: str = "NYSE"
    premarket_open: time = time(4, 0)
    regular_open: time = time(9, 30)
    regular_close: time = time(16, 0)
    afterhours_close: time = time(20, 0)
    early_close_regular_close: time = time(13, 0)
    calendar_source: str = "builtin_us_equity_calendar"
    calendar_source_confidence: str = "medium"
    require_verified_calendar: bool = False


@dataclass(frozen=True)
class CalendarStatus:
    is_trading_day: bool | None
    is_holiday: bool
    is_early_close: bool
    regular_close: time
    calendar_source: str
    calendar_source_confidence: str
    blocked_reason: str = ""


@dataclass(frozen=True)
class MarketSessionSnapshot:
    timestamp_utc: str
    timestamp_new_york: str
    timestamp_local: str
    exchange: str
    calendar_source: str
    calendar_source_confidence: str
    session_state: str
    is_trading_day: bool
    is_weekend: bool
    is_holiday: bool
    is_early_close: bool
    regular_open_et: str
    regular_close_et: str
    premarket_open_et: str
    afterhours_close_et: str
    current_session_start_et: str | None
    current_session_end_et: str | None
    allows_monitoring: bool
    allows_quote_wait: bool
    allows_execution_readiness_check: bool
    allows_protective_order_execution: bool
    expected_live_bid_ask: bool
    blocked_reason: str
    next_session_state: str | None
    next_session_start_et: str | None
    next_regular_open_et: str | None
    contract_details_available: bool
    contract_details_source: str
    symbols: list[dict[str, object]]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def config_from_env() -> MarketSessionConfig:
    return MarketSessionConfig(
        exchange=os.getenv("US_EQUITY_EXCHANGE", "NYSE").strip().upper() or "NYSE",
        premarket_open=_time_env("US_EQUITY_PREMARKET_OPEN_ET", time(4, 0)),
        regular_open=_time_env("US_EQUITY_REGULAR_OPEN_ET", time(9, 30)),
        regular_close=_time_env("US_EQUITY_REGULAR_CLOSE_ET", time(16, 0)),
        afterhours_close=_time_env("US_EQUITY_AFTERHOURS_CLOSE_ET", time(20, 0)),
        early_close_regular_close=_time_env("US_EQUITY_EARLY_CLOSE_ET", time(13, 0)),
        require_verified_calendar=_bool_env("US_EQUITY_REQUIRE_VERIFIED_CALENDAR", False),
    )


def current_market_session(
    *,
    now: datetime | None = None,
    symbols: Sequence[str] | None = None,
    config: MarketSessionConfig | None = None,
    contract_details: Mapping[str, Mapping[str, object]] | None = None,
) -> MarketSessionSnapshot:
    cfg = config or config_from_env()
    current_utc = _as_utc(now or datetime.now(timezone.utc))
    current_ny = current_utc.astimezone(NY)
    current_local = current_utc.astimezone(LOCAL)
    today = current_ny.date()
    is_weekend = current_ny.weekday() >= 5
    calendar = calendar_status(today, config=cfg)
    is_holiday = calendar.is_holiday
    is_early_close = calendar.is_early_close
    trading_day = bool(calendar.is_trading_day) if calendar.is_trading_day is not None else False
    regular_close = calendar.regular_close
    state, start_time, end_time, reason = _state_for_time(
        current_ny.time(),
        trading_day=trading_day,
        is_weekend=is_weekend,
        is_holiday=is_holiday,
        is_early_close=is_early_close,
        config=cfg,
        regular_close=regular_close,
    )
    if calendar.is_trading_day is None:
        state = MarketSessionState.UNKNOWN
        start_time = None
        end_time = None
        reason = calendar.blocked_reason or "market_session_unknown"
    active = state in {
        MarketSessionState.PREMARKET,
        MarketSessionState.REGULAR,
        MarketSessionState.AFTERHOURS,
        MarketSessionState.EARLY_CLOSE,
    }
    next_start = _next_regular_open(current_ny, cfg, _holiday_dates(current_ny.year))
    next_state = MarketSessionState.REGULAR.value if next_start else None
    symbol_rows = _symbol_rows(symbols or (), contract_details or {}, state, active, now_ny=current_ny)
    contract_details_available = any(bool(row.get("ibkr_trading_hours_available")) for row in symbol_rows)
    return MarketSessionSnapshot(
        timestamp_utc=current_utc.isoformat(),
        timestamp_new_york=f"{current_ny.isoformat()} [America/New_York]",
        timestamp_local=f"{current_local.isoformat()} [{LOCAL.key}]",
        exchange=cfg.exchange,
        calendar_source=calendar.calendar_source,
        calendar_source_confidence=calendar.calendar_source_confidence,
        session_state=state.value,
        is_trading_day=trading_day,
        is_weekend=is_weekend,
        is_holiday=is_holiday,
        is_early_close=is_early_close,
        regular_open_et=_fmt_time(cfg.regular_open),
        regular_close_et=_fmt_time(regular_close),
        premarket_open_et=_fmt_time(cfg.premarket_open),
        afterhours_close_et=_fmt_time(cfg.afterhours_close),
        current_session_start_et=_fmt_time(start_time) if start_time else None,
        current_session_end_et=_fmt_time(end_time) if end_time else None,
        allows_monitoring=True,
        allows_quote_wait=active,
        allows_execution_readiness_check=active,
        allows_protective_order_execution=active,
        expected_live_bid_ask=active,
        blocked_reason="" if active else reason,
        next_session_state=next_state,
        next_session_start_et=next_start.isoformat() if next_start else None,
        next_regular_open_et=next_start.isoformat() if next_start else None,
        contract_details_available=contract_details_available,
        contract_details_source="provided_contract_details" if contract_details_available else "not_available",
        symbols=symbol_rows,
    )


def write_market_session_report(
    *,
    now: datetime | None = None,
    symbols: Sequence[str] | None = None,
    contract_details: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, object]:
    snapshot = current_market_session(now=now, symbols=symbols, contract_details=contract_details)
    payload = snapshot.to_dict()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "latest.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    (REPORT_DIR / "latest.md").write_text(market_session_md(payload), encoding="utf-8")
    return payload


def fetch_ibkr_contract_details(
    symbols: Sequence[str],
    *,
    host: str,
    port: int,
    client_id: int,
    timeout: float = 4.0,
) -> dict[str, dict[str, object]]:
    clean_symbols = [symbol.strip().upper() for symbol in symbols if symbol and symbol.strip()]
    if not clean_symbols:
        return {}
    client = _ContractDetailsClient({index + 1: symbol for index, symbol in enumerate(dict.fromkeys(clean_symbols))})
    thread: threading.Thread | None = None
    try:
        client.connect(host, port, clientId=client_id)
        thread = threading.Thread(target=client.run, daemon=True)
        thread.start()
        if not client.ready.wait(timeout):
            return {}
        for req_id, symbol in client.req_id_to_symbol.items():
            client.reqContractDetails(req_id, _stock_contract(symbol))
        client.done.wait(timeout)
        return client.details
    except Exception:
        return {}
    finally:
        try:
            if client.isConnected():
                client.disconnect()
        except Exception:
            pass
        if thread is not None:
            thread.join(timeout=0.5)


def market_session_md(payload: Mapping[str, object]) -> str:
    lines = [
        "# Market Session",
        "",
        f"- timestamp_utc: {payload.get('timestamp_utc')}",
        f"- timestamp_new_york: {payload.get('timestamp_new_york')}",
        f"- exchange: {payload.get('exchange')}",
        f"- calendar_source: {payload.get('calendar_source')}",
        f"- session_state: {payload.get('session_state')}",
        f"- is_trading_day: {payload.get('is_trading_day')}",
        f"- is_weekend: {payload.get('is_weekend')}",
        f"- is_holiday: {payload.get('is_holiday')}",
        f"- is_early_close: {payload.get('is_early_close')}",
        f"- expected_live_bid_ask: {payload.get('expected_live_bid_ask')}",
        f"- allows_quote_wait: {payload.get('allows_quote_wait')}",
        f"- allows_execution_readiness_check: {payload.get('allows_execution_readiness_check')}",
        f"- allows_protective_order_execution: {payload.get('allows_protective_order_execution')}",
        f"- blocked_reason: {payload.get('blocked_reason')}",
        f"- next_regular_open_et: {payload.get('next_regular_open_et')}",
        "",
        "## Hours",
        "",
        f"- premarket_open_et: {payload.get('premarket_open_et')}",
        f"- regular_open_et: {payload.get('regular_open_et')}",
        f"- regular_close_et: {payload.get('regular_close_et')}",
        f"- afterhours_close_et: {payload.get('afterhours_close_et')}",
    ]
    rows = payload.get("symbols") or []
    if isinstance(rows, list) and rows:
        lines.extend(["", "## Symbols", "", "| Symbol | Expected Bid/Ask | IBKR Hours | Contract State | Contract Blocked Reason |", "|---|---|---|---|---|"])
        for row in rows:
            if isinstance(row, Mapping):
                lines.append(
                    f"| {row.get('symbol')} | {row.get('expected_live_bid_ask')} | "
                    f"{row.get('ibkr_trading_hours_available')} | {row.get('contract_session_state')} | "
                    f"{row.get('contract_blocked_reason')} |"
                )
    return "\n".join(lines) + "\n"


def classify_streaming_bid_ask_gap(*, last_received: bool, close_received: bool) -> str:
    snapshot = current_market_session()
    if snapshot.expected_live_bid_ask:
        return "streaming_no_bid_ask_received" if (last_received or close_received) else "outside_session_no_quote"
    if snapshot.session_state in {MarketSessionState.WEEKEND.value, MarketSessionState.HOLIDAY.value, MarketSessionState.CLOSED.value}:
        return "market_closed_no_active_bid_ask"
    if snapshot.session_state == MarketSessionState.UNKNOWN.value:
        return "market_session_unknown"
    return "outside_session_no_quote"


def parse_ibkr_trading_hours(value: str) -> list[dict[str, object]]:
    """Parse an IBKR tradingHours/liquidHours string into reportable rows.

    Example segment: ``20260710:0400-2000`` or ``20260711:CLOSED``.
    Time zones are provided by ContractDetails separately; callers should label
    the source time zone in the surrounding report.
    """

    rows: list[dict[str, object]] = []
    for segment in value.split(";"):
        segment = segment.strip()
        if not segment or ":" not in segment:
            continue
        raw_day, raw_hours = segment.split(":", 1)
        if raw_hours.upper() == "CLOSED":
            rows.append({"date": raw_day, "closed": True, "start": None, "end": None})
            continue
        for window in raw_hours.split(","):
            if "-" not in window:
                continue
            start, end = window.split("-", 1)
            rows.append({"date": raw_day, "closed": False, "start": start, "end": end})
    return rows


class _ContractDetailsClient(EWrapper, EClient):
    def __init__(self, req_id_to_symbol: Mapping[int, str]) -> None:
        EClient.__init__(self, self)
        self.req_id_to_symbol = dict(req_id_to_symbol)
        self.ready = threading.Event()
        self.done = threading.Event()
        self.details: dict[str, dict[str, object]] = {}
        self._completed: set[int] = set()

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.ready.set()

    def contractDetails(self, reqId: int, contractDetails: object) -> None:  # noqa: N802,N803
        symbol = self.req_id_to_symbol.get(reqId)
        if symbol is None:
            return
        self.details[symbol] = {
            "timeZoneId": getattr(contractDetails, "timeZoneId", None),
            "tradingHours": getattr(contractDetails, "tradingHours", None),
            "liquidHours": getattr(contractDetails, "liquidHours", None),
        }

    def contractDetailsEnd(self, reqId: int) -> None:  # noqa: N802
        self._completed.add(reqId)
        if self._completed >= set(self.req_id_to_symbol):
            self.done.set()

    def error(self, reqId: int, *args: object) -> None:
        self._completed.add(reqId)
        if self._completed >= set(self.req_id_to_symbol):
            self.done.set()


def _stock_contract(symbol: str) -> Contract:
    contract = Contract()
    contract.symbol = symbol
    contract.secType = "STK"
    contract.exchange = "SMART"
    contract.currency = "USD"
    return contract


def calendar_status(day: date, *, config: MarketSessionConfig | None = None) -> CalendarStatus:
    cfg = config or config_from_env()
    if day.weekday() >= 5:
        return CalendarStatus(
            is_trading_day=False,
            is_holiday=False,
            is_early_close=False,
            regular_close=cfg.regular_close,
            calendar_source="weekend_rule",
            calendar_source_confidence="high",
        )
    package_status = _calendar_status_from_package(day, cfg)
    if package_status is not None:
        return package_status
    local_status = _calendar_status_from_local_file(day, cfg)
    if local_status is not None:
        return local_status
    if cfg.require_verified_calendar:
        return CalendarStatus(
            is_trading_day=None,
            is_holiday=False,
            is_early_close=False,
            regular_close=cfg.regular_close,
            calendar_source="verified_calendar_unavailable",
            calendar_source_confidence="low",
            blocked_reason="market_session_unknown",
        )
    holidays = _holiday_dates(day.year)
    early_closes = _early_close_dates(day.year)
    is_holiday = day in holidays
    is_early_close = day in early_closes and not is_holiday
    return CalendarStatus(
        is_trading_day=not is_holiday,
        is_holiday=is_holiday,
        is_early_close=is_early_close,
        regular_close=cfg.early_close_regular_close if is_early_close else cfg.regular_close,
        calendar_source=cfg.calendar_source,
        calendar_source_confidence=cfg.calendar_source_confidence,
    )


def _state_for_time(
    current: time,
    *,
    trading_day: bool,
    is_weekend: bool,
    is_holiday: bool,
    is_early_close: bool,
    config: MarketSessionConfig,
    regular_close: time,
) -> tuple[MarketSessionState, time | None, time | None, str]:
    if is_weekend:
        return MarketSessionState.WEEKEND, None, None, "market_weekend_no_live_bid_ask_expected"
    if is_holiday:
        return MarketSessionState.HOLIDAY, None, None, "market_holiday_no_live_bid_ask_expected"
    if not trading_day:
        return MarketSessionState.UNKNOWN, None, None, "market_session_unknown"
    if config.premarket_open <= current < config.regular_open:
        return MarketSessionState.PREMARKET, config.premarket_open, config.regular_open, ""
    if config.regular_open <= current < regular_close:
        if is_early_close:
            return MarketSessionState.EARLY_CLOSE, config.regular_open, regular_close, ""
        return MarketSessionState.REGULAR, config.regular_open, regular_close, ""
    if regular_close <= current < config.afterhours_close and not is_early_close:
        return MarketSessionState.AFTERHOURS, regular_close, config.afterhours_close, ""
    return MarketSessionState.CLOSED, None, None, "market_closed_no_live_bid_ask_expected"


def _symbol_rows(
    symbols: Iterable[str],
    contract_details: Mapping[str, Mapping[str, object]],
    state: MarketSessionState,
    active: bool,
    *,
    now_ny: datetime,
) -> list[dict[str, object]]:
    rows = []
    for raw in symbols:
        symbol = str(raw).strip().upper()
        if not symbol:
            continue
        details = contract_details.get(symbol, {})
        trading_hours = str(details.get("tradingHours") or details.get("trading_hours") or "")
        liquid_hours = str(details.get("liquidHours") or details.get("liquid_hours") or "")
        trading_today = _hours_today(trading_hours, now_ny.date())
        liquid_today = _hours_today(liquid_hours, now_ny.date())
        contract_trading_open = _hours_allow_now(trading_today, now_ny)
        contract_liquid_open = _hours_allow_now(liquid_today, now_ny)
        contract_state = state.value
        contract_reason = "" if active else _inactive_reason(state)
        if trading_today and all(row.get("closed") for row in trading_today):
            contract_state = "CLOSED"
            contract_trading_open = False
            contract_reason = "ibkr_contract_details_trading_hours_closed"
        elif details and not contract_trading_open:
            contract_state = "CLOSED"
            contract_reason = "ibkr_contract_details_not_open_now"
        conflict = bool(details) and (
            (not active and contract_trading_open)
            or (active and contract_state == "CLOSED")
        )
        if conflict:
            contract_reason = "calendar_contract_session_conflict"
        rows.append(
            {
                "symbol": symbol,
                "session_state": state.value,
                "expected_live_bid_ask": active,
                "ibkr_trading_hours_available": bool(trading_hours or liquid_hours),
                "time_zone_id": details.get("timeZoneId") or details.get("time_zone"),
                "trading_hours_today": trading_today,
                "liquid_hours_today": liquid_today,
                "contract_session_state": contract_state,
                "contract_allows_trading_now": contract_trading_open if details else None,
                "contract_allows_regular_liquidity_now": contract_liquid_open if details else None,
                "contract_blocked_reason": contract_reason,
                "calendar_contract_conflict": conflict,
                "contract_details_available": bool(details),
                "contract_time_zone": details.get("timeZoneId") or details.get("time_zone"),
                "trading_hours": trading_hours or None,
                "liquid_hours": liquid_hours or None,
                "parsed_trading_hours": parse_ibkr_trading_hours(trading_hours) if trading_hours else [],
                "parsed_liquid_hours": parse_ibkr_trading_hours(liquid_hours) if liquid_hours else [],
                "blocked_reason": "" if active else _inactive_reason(state),
            }
        )
    return rows


def _hours_today(value: str, day: date) -> list[dict[str, object]]:
    day_key = day.strftime("%Y%m%d")
    return [row for row in parse_ibkr_trading_hours(value) if row.get("date") == day_key]


def _hours_allow_now(rows: Sequence[Mapping[str, object]], current_ny: datetime) -> bool:
    if not rows:
        return False
    current_minutes = current_ny.hour * 60 + current_ny.minute
    for row in rows:
        if row.get("closed"):
            continue
        start = _hhmm_to_minutes(str(row.get("start") or ""))
        end = _hhmm_to_minutes(str(row.get("end") or ""))
        if start is not None and end is not None and start <= current_minutes < end:
            return True
    return False


def _hhmm_to_minutes(value: str) -> int | None:
    if len(value) != 4 or not value.isdigit():
        return None
    return int(value[:2]) * 60 + int(value[2:])


def _calendar_status_from_package(day: date, cfg: MarketSessionConfig) -> CalendarStatus | None:
    try:
        import exchange_calendars as xcals  # type: ignore[import-not-found]

        calendar = xcals.get_calendar("XNYS")
        schedule = calendar.schedule.loc[str(day):str(day)]
        if schedule.empty:
            return CalendarStatus(False, True, False, cfg.regular_close, "exchange_calendars:XNYS", "high")
        close_ts = schedule.iloc[0]["market_close"]
        close_ny = close_ts.to_pydatetime().astimezone(NY)
        is_early = close_ny.time() < cfg.regular_close
        return CalendarStatus(True, False, is_early, close_ny.time().replace(second=0, microsecond=0), "exchange_calendars:XNYS", "high")
    except Exception:
        pass
    try:
        import pandas_market_calendars as mcal  # type: ignore[import-not-found]

        calendar = mcal.get_calendar("NYSE")
        schedule = calendar.schedule(start_date=day.isoformat(), end_date=day.isoformat())
        if schedule.empty:
            return CalendarStatus(False, True, False, cfg.regular_close, "pandas_market_calendars:NYSE", "high")
        close_ts = schedule.iloc[0]["market_close"]
        close_ny = close_ts.to_pydatetime().astimezone(NY)
        is_early = close_ny.time() < cfg.regular_close
        return CalendarStatus(True, False, is_early, close_ny.time().replace(second=0, microsecond=0), "pandas_market_calendars:NYSE", "high")
    except Exception:
        return None


def _calendar_status_from_local_file(day: date, cfg: MarketSessionConfig) -> CalendarStatus | None:
    for path in [
        PROJECT_ROOT / "config" / "us_equity_market_calendar.json",
        PROJECT_ROOT / "data" / "us_equity_market_calendar.json",
    ]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            continue
        holidays = set(payload.get("holidays", []))
        early_closes = payload.get("early_closes", {})
        key = day.isoformat()
        if key in holidays:
            return CalendarStatus(False, True, False, cfg.regular_close, f"local_calendar:{path}", "high")
        if key in early_closes:
            return CalendarStatus(True, False, True, _parse_time(str(early_closes[key]), cfg.early_close_regular_close), f"local_calendar:{path}", "high")
        return CalendarStatus(True, False, False, cfg.regular_close, f"local_calendar:{path}", "medium")
    return None


def _inactive_reason(state: MarketSessionState) -> str:
    if state == MarketSessionState.WEEKEND:
        return "market_weekend_no_live_bid_ask_expected"
    if state == MarketSessionState.HOLIDAY:
        return "market_holiday_no_live_bid_ask_expected"
    if state == MarketSessionState.UNKNOWN:
        return "market_session_unknown"
    return "market_closed_no_live_bid_ask_expected"


def _next_regular_open(current_ny: datetime, config: MarketSessionConfig, holidays: set[date]) -> datetime | None:
    for offset in range(0, 14):
        candidate = current_ny.date() + timedelta(days=offset)
        if candidate.weekday() >= 5 or candidate in holidays:
            continue
        open_dt = datetime.combine(candidate, config.regular_open, tzinfo=NY)
        if open_dt > current_ny:
            return open_dt
    return None


def _holiday_dates(year: int) -> set[date]:
    holidays = {
        _observed(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _good_friday(year),
        _last_weekday(year, 5, 0),
        _observed(date(year, 6, 19)),
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _observed(date(year, 12, 25)),
    }
    return {item for item in holidays if item.year == year}


def _early_close_dates(year: int) -> set[date]:
    candidates = {
        _nth_weekday(year, 11, 3, 4) + timedelta(days=1),
        date(year, 12, 24),
    }
    july_four = date(year, 7, 4)
    if july_four.weekday() == 5:
        candidates.add(date(year, 7, 3))
    elif july_four.weekday() in {1, 2, 3, 4}:
        candidates.add(july_four - timedelta(days=1))
    return {item for item in candidates if item.year == year and item.weekday() < 5}


def _observed(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> date:
    first = date(year, month, 1)
    days = (weekday - first.weekday()) % 7
    return first + timedelta(days=days + 7 * (nth - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        current = date(year, 12, 31)
    else:
        current = date(year, month + 1, 1) - timedelta(days=1)
    while current.weekday() != weekday:
        current -= timedelta(days=1)
    return current


def _good_friday(year: int) -> date:
    # Anonymous Gregorian computus.
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day) - timedelta(days=2)


def _time_env(name: str, default: time) -> time:
    raw = os.getenv(name)
    if not raw:
        return default
    return _parse_time(raw, default)


def _parse_time(raw: str, default: time) -> time:
    try:
        hour, minute = raw.strip().split(":", 1)
    except ValueError:
        return default
    return time(int(hour), int(minute))


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _fmt_time(value: time) -> str:
    return value.strftime("%H:%M")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
