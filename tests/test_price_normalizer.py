import unittest

from trading.price_normalizer import normalize_order_price_record


class PriceNormalizerTests(unittest.TestCase):
    def test_buy_limit_floors_to_cent(self) -> None:
        record = normalize_order_price_record(
            symbol="AAPL",
            side="BUY",
            order_type="LMT",
            price=100.019,
        )
        self.assertEqual(record.normalized_price, 100.01)
        self.assertEqual(record.rounding_direction, "floor")

    def test_sell_limit_ceils_to_cent(self) -> None:
        record = normalize_order_price_record(
            symbol="AAPL",
            side="SELL",
            order_type="LMT",
            price=100.011,
        )
        self.assertEqual(record.normalized_price, 100.02)
        self.assertEqual(record.rounding_direction, "ceil")

    def test_sell_stop_floors_to_valid_protective_stop(self) -> None:
        record = normalize_order_price_record(
            symbol="PFE",
            side="SELL",
            order_type="STP",
            price=24.129,
        )
        self.assertEqual(record.normalized_price, 24.12)
        self.assertEqual(record.rounding_direction, "floor")

    def test_buy_stop_ceils_to_cent(self) -> None:
        record = normalize_order_price_record(
            symbol="AAPL",
            side="BUY",
            order_type="STP",
            price=100.011,
        )
        self.assertEqual(record.normalized_price, 100.02)

    def test_custom_tick_size(self) -> None:
        record = normalize_order_price_record(
            symbol="TEST",
            side="BUY",
            order_type="LMT",
            price=10.07,
            min_tick=0.05,
        )
        self.assertEqual(record.normalized_price, 10.05)


if __name__ == "__main__":
    unittest.main()
