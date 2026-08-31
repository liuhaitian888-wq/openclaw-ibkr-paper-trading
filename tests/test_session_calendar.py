import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from trading.session_calendar import TradingSession, classify_trading_session


ET = ZoneInfo("America/New_York")


class SessionCalendarTests(unittest.TestCase):
    def test_regular_session_classification(self) -> None:
        snapshot = classify_trading_session(datetime(2026, 7, 8, 10, 0, tzinfo=ET))

        self.assertEqual(snapshot.session, TradingSession.REGULAR_PAPER)
        self.assertIn("Europe/Berlin", snapshot.berlin_time)

    def test_premarket_session_classification(self) -> None:
        snapshot = classify_trading_session(datetime(2026, 7, 8, 8, 0, tzinfo=ET))

        self.assertEqual(snapshot.session, TradingSession.PREMARKET_PAPER)

    def test_afterhours_session_classification(self) -> None:
        snapshot = classify_trading_session(datetime(2026, 7, 8, 17, 0, tzinfo=ET))

        self.assertEqual(snapshot.session, TradingSession.AFTERHOURS_PAPER)

    def test_overnight_session_classification(self) -> None:
        snapshot = classify_trading_session(datetime(2026, 7, 8, 21, 0, tzinfo=ET))

        self.assertEqual(snapshot.session, TradingSession.OVERNIGHT_PAPER)

    def test_weekend_offline_classification(self) -> None:
        snapshot = classify_trading_session(datetime(2026, 7, 11, 12, 0, tzinfo=ET))

        self.assertEqual(snapshot.session, TradingSession.OFFLINE)


if __name__ == "__main__":
    unittest.main()
