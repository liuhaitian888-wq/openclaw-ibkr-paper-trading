import unittest
from datetime import datetime, timedelta, timezone

from trading.market_data import Quote
from trading.models import TradeProposal
from trading.session_calendar import TradingSession
from trading.session_policy import SessionOrderContext, policy_for_session, validate_session_order


class SessionPolicyTests(unittest.TestCase):
    def test_outside_rth_only_for_extended_sessions(self) -> None:
        self.assertFalse(policy_for_session(TradingSession.REGULAR_PAPER).outside_rth)
        self.assertTrue(policy_for_session(TradingSession.PREMARKET_PAPER).outside_rth)
        self.assertTrue(policy_for_session(TradingSession.AFTERHOURS_PAPER).outside_rth)

    def test_protective_stop_required(self) -> None:
        decision = validate_session_order(
            TradeProposal("AAPL", "BUY", 1, 100.0, None, "key-0001"),
            policy_for_session(TradingSession.REGULAR_PAPER),
            SessionOrderContext(quote=_quote(), open_orders=[]),
        )

        self.assertFalse(decision.approved)
        self.assertIn("protective stop", decision.reason)

    def test_stale_quote_blocks_order(self) -> None:
        decision = validate_session_order(
            TradeProposal("AAPL", "BUY", 1, 100.0, 99.0, "key-0001"),
            policy_for_session(TradingSession.REGULAR_PAPER),
            SessionOrderContext(
                quote=Quote("AAPL", 100.0, datetime.now(timezone.utc) - timedelta(seconds=60), "test", bid=99.99, ask=100.01),
                open_orders=[],
            ),
        )

        self.assertFalse(decision.approved)
        self.assertIn("stale", decision.reason)

    def test_open_order_blocks_duplicate_submit(self) -> None:
        proposal = TradeProposal("AAPL", "BUY", 1, 100.0, 99.0, "key-0001")
        decision = validate_session_order(
            proposal,
            policy_for_session(TradingSession.REGULAR_PAPER),
            SessionOrderContext(
                quote=_quote(),
                open_orders=[{"symbol": "AAPL", "action": "BUY", "order_ref": "key-0001"}],
            ),
        )

        self.assertFalse(decision.approved)
        self.assertIn("duplicate", decision.reason)

    def test_max_orders_per_symbol_blocks_order(self) -> None:
        proposal = TradeProposal("AAPL", "BUY", 1, 100.0, 99.0, "key-0001")
        policy = policy_for_session(TradingSession.REGULAR_PAPER)
        decision = validate_session_order(
            proposal,
            policy,
            SessionOrderContext(
                quote=_quote(),
                open_orders=[],
                orders_submitted_by_symbol={"AAPL": policy.max_orders_per_symbol},
            ),
        )

        self.assertFalse(decision.approved)
        self.assertIn("symbol", decision.reason)


def _quote() -> Quote:
    return Quote("AAPL", 100.0, datetime.now(timezone.utc), "test", bid=99.99, ask=100.01, volume=1000)


if __name__ == "__main__":
    unittest.main()
