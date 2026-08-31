from dataclasses import dataclass
from datetime import datetime, time, timezone
from enum import Enum
from zoneinfo import ZoneInfo


US_EASTERN = ZoneInfo("America/New_York")
EUROPE_BERLIN = ZoneInfo("Europe/Berlin")


class TradingSession(str, Enum):
    OFFLINE = "OFFLINE"
    OVERNIGHT_PAPER = "OVERNIGHT_PAPER"
    PREMARKET_PAPER = "PREMARKET_PAPER"
    REGULAR_PAPER = "REGULAR_PAPER"
    AFTERHOURS_PAPER = "AFTERHOURS_PAPER"


@dataclass(frozen=True)
class SessionSnapshot:
    session: TradingSession
    utc_time: str
    eastern_time: str
    berlin_time: str
    is_trading_day: bool
    reason: str


def classify_trading_session(now: datetime | None = None) -> SessionSnapshot:
    current_utc = _as_utc(now or datetime.now(timezone.utc))
    eastern = current_utc.astimezone(US_EASTERN)
    berlin = current_utc.astimezone(EUROPE_BERLIN)
    session, reason = _session_for_eastern(eastern)
    return SessionSnapshot(
        session=session,
        utc_time=current_utc.isoformat(),
        eastern_time=f"{eastern.isoformat()} [America/New_York]",
        berlin_time=f"{berlin.isoformat()} [Europe/Berlin]",
        is_trading_day=eastern.weekday() < 5,
        reason=reason,
    )


def _session_for_eastern(eastern: datetime) -> tuple[TradingSession, str]:
    weekday = eastern.weekday()
    current = eastern.time()
    if weekday == 6 and current >= time(20, 0):
        return TradingSession.OVERNIGHT_PAPER, "Sunday overnight session"
    if weekday in {0, 1, 2, 3} and current >= time(20, 0):
        return TradingSession.OVERNIGHT_PAPER, "Weekday overnight session"
    if weekday in {0, 1, 2, 3, 4} and current < time(3, 50):
        return TradingSession.OVERNIGHT_PAPER, "Overnight session before 03:50 ET"
    if weekday >= 5:
        return TradingSession.OFFLINE, "Weekend outside supported overnight window"
    if time(4, 0) <= current < time(9, 30):
        return TradingSession.PREMARKET_PAPER, "Premarket session"
    if time(9, 30) <= current < time(16, 0):
        return TradingSession.REGULAR_PAPER, "Regular trading session"
    if time(16, 0) <= current < time(20, 0):
        return TradingSession.AFTERHOURS_PAPER, "After-hours session"
    return TradingSession.OFFLINE, "No paper trading session policy is active"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
