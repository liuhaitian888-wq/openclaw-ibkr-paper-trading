import unittest

from scripts.refresh_position_protection_test_result import refresh_result


class PositionProtectionTestResultRefreshTests(unittest.TestCase):
    def test_plain_stp_outside_rth_false_is_success_with_warning(self) -> None:
        result = {
            "symbol": "PFE",
            "order_ref": "protect-pfe-test",
            "side": "SELL",
            "order_type": "STP",
            "tif": "GTC",
            "outside_rth": True,
            "outsideRth_requested": True,
            "checks": {
                "active_protective_sell_stp": False,
                "side_sell": True,
                "order_type_stp": True,
                "tif_gtc": True,
                "outside_rth_requested": True,
                "outside_rth_effective_or_explained": False,
                "order_ref_exists": True,
                "qty_correct": True,
                "stop_price_matches_preview": True,
                "coverage_after_gt_before": True,
                "uncovered_qty_reduced": True,
                "no_buy_submitted": True,
                "live_not_enabled": True,
            },
        }
        refreshed = refresh_result(
            result,
            {
                "open_orders": [
                    {
                        "symbol": "PFE",
                        "action": "SELL",
                        "order_type": "STP",
                        "tif": "GTC",
                        "outside_rth": False,
                        "order_ref": "protect-pfe-test",
                        "status": "PreSubmitted",
                        "order_status": {"status": "PreSubmitted"},
                    }
                ]
            },
        )
        self.assertTrue(refreshed["success"])
        self.assertTrue(refreshed["success_with_warning"])
        self.assertFalse(refreshed["blocks_run"])
        self.assertFalse(refreshed["outsideRth_supported"])
        self.assertEqual(refreshed["outsideRth_warning_reason"], "IBKR/TWS plain STP appears RTH-only")


if __name__ == "__main__":
    unittest.main()
