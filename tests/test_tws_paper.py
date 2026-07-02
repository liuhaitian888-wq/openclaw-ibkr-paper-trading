from decimal import Decimal
import unittest

from trading.models import TradeProposal
from trading.tws_paper import OrderConfirmation, TwsPaperBroker, TwsPaperClient


class TwsPaperBrokerTests(unittest.TestCase):
    def test_transmitted_order_requires_order_status_ack(self) -> None:
        client = TwsPaperClient()
        client.expected_order_ids = {100}

        client.openOrder(100, object(), object(), object())

        self.assertEqual(client.acknowledged_order_ids, set())
        self.assertFalse(client.orders_acknowledged.is_set())

        client.orderStatus(
            100,
            "Submitted",
            Decimal("0"),
            Decimal("1"),
            0.0,
            0,
            0,
            0.0,
            0,
            "",
            0.0,
        )

        self.assertEqual(client.acknowledged_order_ids, {100})
        self.assertTrue(client.orders_acknowledged.is_set())

    def test_staged_order_can_ack_from_open_order(self) -> None:
        client = TwsPaperClient()
        client.expected_order_ids = {100}
        client.allow_open_order_confirmation = True

        client.openOrder(100, object(), object(), object())

        self.assertEqual(client.acknowledged_order_ids, {100})
        self.assertTrue(client.orders_acknowledged.is_set())

    def test_bracket_has_protective_stop_and_no_transmission_by_default(self) -> None:
        proposal = TradeProposal(
            "AAPL",
            "BUY",
            1,
            190.0,
            185.0,
            "trade-0001",
        )

        parent, stop = TwsPaperBroker._bracket_orders(
            proposal,
            "DU12345",
            100,
            101,
            transmit=False,
        )

        self.assertEqual(parent.action, "BUY")
        self.assertEqual(parent.orderType, "LMT")
        self.assertFalse(parent.transmit)
        self.assertEqual(stop.action, "SELL")
        self.assertEqual(stop.orderType, "STP")
        self.assertEqual(stop.parentId, 100)
        self.assertFalse(stop.transmit)
        self.assertFalse(parent.outsideRth)
        self.assertFalse(stop.outsideRth)

    def test_transmitted_bracket_only_transmits_on_final_stop_child(self) -> None:
        proposal = TradeProposal(
            "AAPL",
            "BUY",
            1,
            190.0,
            185.0,
            "trade-0002",
        )

        parent, stop = TwsPaperBroker._bracket_orders(
            proposal,
            "DU12345",
            100,
            101,
            transmit=True,
        )

        self.assertFalse(parent.transmit)
        self.assertTrue(stop.transmit)

    def test_outside_rth_is_configurable_for_both_bracket_legs(self) -> None:
        proposal = TradeProposal(
            "AAPL",
            "BUY",
            1,
            190.0,
            185.0,
            "trade-0003",
        )

        parent, stop = TwsPaperBroker._bracket_orders(
            proposal,
            "DU12345",
            100,
            101,
            transmit=True,
            outside_rth=True,
        )

        self.assertTrue(parent.outsideRth)
        self.assertTrue(stop.outsideRth)

    def test_limit_order_can_transmit_outside_rth_without_stop_leg(self) -> None:
        proposal = TradeProposal(
            "MSFT",
            "BUY",
            1,
            300.0,
            None,
            "trade-0004",
        )

        order = TwsPaperBroker._limit_order(
            proposal,
            "DU12345",
            100,
            transmit=True,
            outside_rth=True,
        )

        self.assertEqual(order.action, "BUY")
        self.assertEqual(order.orderType, "LMT")
        self.assertEqual(order.totalQuantity, 1)
        self.assertEqual(order.lmtPrice, 300.0)
        self.assertTrue(order.transmit)
        self.assertTrue(order.outsideRth)

    def test_order_confirmation_records_partial_ack_as_pending(self) -> None:
        confirmation = OrderConfirmation(
            order_ids=(10, 11),
            acknowledged_order_ids=(10,),
            messages=("request=11, details=(11, 399, 'Order Event Warning', '')",),
            timings={"broker_total_ms": 12.5},
        )

        self.assertTrue(confirmation.pending_confirmation)
        self.assertEqual(confirmation.acknowledged_ids, (10,))
        self.assertEqual(confirmation.timings["broker_total_ms"], 12.5)
        details = confirmation.details()
        self.assertIn("pending_confirmation=true", details)
        self.assertIn("acknowledged_order_ids=[10]", details)

    def test_order_event_warning_is_not_fatal_order_error(self) -> None:
        client = TwsPaperClient()
        client.errors.append(
            "request=12, details=(12, 399, 'Order Event Warning: outside RTH', '')"
        )

        self.assertEqual(TwsPaperBroker._fatal_order_errors(client, {12}), [])

        client.errors.append("request=12, details=(12, 201, 'Order rejected', '')")
        fatal = TwsPaperBroker._fatal_order_errors(client, {12})
        self.assertEqual(len(fatal), 1)
        self.assertIn("Order rejected", fatal[0])


if __name__ == "__main__":
    unittest.main()
