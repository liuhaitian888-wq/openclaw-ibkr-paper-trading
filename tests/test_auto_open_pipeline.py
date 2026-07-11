import unittest

from trading.auto_open_pipeline import PipelineConfig, run_auto_open_pipeline


class AutoOpenPipelineTests(unittest.TestCase):
    def test_defaults_enable_discovery_news_pool_intent_and_simulation_safely(self) -> None:
        config = PipelineConfig()
        result = run_auto_open_pipeline("unit-test", config=config)
        audit = result["final_audit"]

        self.assertTrue(audit["discovery_enabled"])
        self.assertTrue(audit["scanner_enabled"])
        self.assertTrue(audit["news_enabled"])
        self.assertTrue(audit["pool_expansion_enabled"])
        self.assertTrue(audit["intent_generation_enabled"])
        self.assertTrue(audit["local_simulation_enabled"])
        self.assertEqual(audit["ibkr_paper_orders_submitted"], 0)
        self.assertEqual(audit["live_orders_submitted"], 0)
        self.assertFalse(audit["paid_snapshot_used"])
        self.assertFalse(audit["regulatory_snapshot_used"])
        self.assertFalse(audit["market_order_used"])

    def test_unavailable_ibkr_news_does_not_fail_pipeline(self) -> None:
        result = run_auto_open_pipeline("unit-news", config=PipelineConfig())

        statuses = {row["status"] for row in result["news"]["interface_tests"]}
        self.assertTrue(statuses)
        self.assertGreaterEqual(len(result["news"]["raw_news_events"]), 1)
        self.assertEqual(result["simulation"]["ibkr_paper_orders_submitted"], 0)

    def test_scanner_news_and_fast_guidance_cannot_submit_orders(self) -> None:
        result = run_auto_open_pipeline("unit-isolation", config=PipelineConfig())

        self.assertFalse(result["scanner"]["scanner_can_submit_orders"])
        self.assertFalse(result["news"]["news_can_submit_orders"])
        self.assertFalse(result["guidance"]["fast_guidance_can_submit_orders"])
        self.assertTrue(all(not row["allowed_to_submit_order"] for row in result["guidance"]["records"]))
        self.assertEqual(result["order_intent_router"]["order_submitted_count"], 0)

    def test_candidates_pass_pool_layers_and_have_scores(self) -> None:
        result = run_auto_open_pipeline("unit-pool", config=PipelineConfig())
        pool = result["pool"]

        self.assertTrue(pool["scanner_news_external_cannot_bypass_layers"])
        self.assertGreater(pool["pool_counts"]["discovery_universe"], 0)
        self.assertGreater(pool["pool_counts"]["trade_pool"], 0)
        first = pool["top_candidates"][0]
        self.assertIn("scanner_score", first["components"])
        self.assertIn("source_details", first)

    def test_simulation_creates_only_local_simulated_orders(self) -> None:
        result = run_auto_open_pipeline("unit-simulation", config=PipelineConfig())
        simulation = result["simulation"]

        self.assertEqual(simulation["mode"], "LOCAL_SIMULATION_ONLY")
        self.assertGreaterEqual(simulation["simulated_orders_count"], 1)
        self.assertTrue(all(row["status"] == "SIMULATED_ORDER" for row in simulation["simulated_orders"]))
        self.assertTrue(all(not row["ibkr_paper_order_submitted"] for row in simulation["simulated_orders"]))
        self.assertTrue(all(not row["live_order_submitted"] for row in simulation["simulated_orders"]))

    def test_paper_execution_interface_defaults_false(self) -> None:
        result = run_auto_open_pipeline("unit-paper-gate", config=PipelineConfig())
        gate = result["paper_execution_gate"]

        self.assertTrue(gate["paper_execution_interface_exists"])
        self.assertFalse(gate["paper_execution_enabled"])
        self.assertFalse(gate["IBKR_PAPER_ORDER_SUBMISSION"])
        self.assertFalse(gate["LIVE_TRADING_ENABLED"])

    def test_safety_config_rejects_real_execution_flags(self) -> None:
        with self.assertRaises(RuntimeError):
            run_auto_open_pipeline("bad-live", config=PipelineConfig(live_trading_enabled=True))
        with self.assertRaises(RuntimeError):
            run_auto_open_pipeline("bad-paper", config=PipelineConfig(ibkr_paper_order_submission=True))
        with self.assertRaises(RuntimeError):
            run_auto_open_pipeline("bad-market", config=PipelineConfig(allow_market_orders=True))
        with self.assertRaises(RuntimeError):
            run_auto_open_pipeline("bad-snapshot", config=PipelineConfig(allow_paid_snapshot=True))
        with self.assertRaises(RuntimeError):
            run_auto_open_pipeline("bad-regsnap", config=PipelineConfig(allow_regulatory_snapshot=True))

    def test_buy_sell_share_same_cycle_snapshot_refs(self) -> None:
        result = run_auto_open_pipeline("unit-refs", config=PipelineConfig())

        self.assertTrue(result["order_intent_router"]["buy_sell_use_same_cycle_snapshot_refs"])
        self.assertIn("account_state_ref", result["order_intent_router"]["snapshot_refs"])
        self.assertIn("scanner_state_ref", result["order_intent_router"]["snapshot_refs"])


if __name__ == "__main__":
    unittest.main()
