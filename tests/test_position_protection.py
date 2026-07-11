import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from trading.position_guard import evaluate_protection_status
from trading.module_interfaces import ForceRefreshResult
from trading.position_protection import (
    build_repair_preview_proposal,
    build_repair_preview_report,
    calculate_dynamic_stop,
    calculate_raw_stop_price,
    calculate_uncovered_qty,
    select_test_then_bulk_symbol,
    StopConfig,
    run_position_protection,
)
from trading.price_normalizer import normalize_order_price


class PositionProtectionTests(unittest.TestCase):
    def _fresh_ok(self) -> ForceRefreshResult:
        return ForceRefreshResult(True, True, True, True, True, True, True, True, "")

    def test_missing_stop_detection(self) -> None:
        result = evaluate_protection_status(position_qty=10, protective_stop_qty=0, protective_stop_orders=[])
        self.assertTrue(result.missing_stop_warning)
        self.assertEqual(result.recommended_action, "create_protective_sell_stop")

    def test_underprotected_detection(self) -> None:
        result = evaluate_protection_status(position_qty=10, protective_stop_qty=4, protective_stop_orders=[{"order_id": 1}])
        self.assertTrue(result.underprotected_warning)
        self.assertEqual(result.recommended_action, "create_additional_protective_sell_stop_for_uncovered_qty")

    def test_fully_protected_detection(self) -> None:
        result = evaluate_protection_status(position_qty=10, protective_stop_qty=10, protective_stop_orders=[{"order_id": 1}])
        self.assertTrue(result.position_covered_by_stop)
        self.assertFalse(result.risk_action_needed)

    def test_overprotected_detection(self) -> None:
        result = evaluate_protection_status(position_qty=10, protective_stop_qty=11, protective_stop_orders=[{"order_id": 1}])
        self.assertTrue(result.overprotected_warning)
        self.assertEqual(result.recommended_action, "review_duplicate_or_excess_stop")

    def test_duplicate_stop_detection(self) -> None:
        result = evaluate_protection_status(
            position_qty=10,
            protective_stop_qty=10,
            protective_stop_orders=[{"order_id": 1}, {"order_id": 2}],
        )
        self.assertTrue(result.duplicate_stop_warning)

    def test_protective_sell_stop_quantity_calculation(self) -> None:
        self.assertEqual(calculate_uncovered_qty(10, 4), 6)
        self.assertEqual(calculate_uncovered_qty(10, 12), 0)
        self.assertEqual(calculate_uncovered_qty(0, 0), 0)

    def test_stop_price_normalization(self) -> None:
        self.assertEqual(normalize_order_price(symbol="T", side="SELL", order_type="STP", price=20.899, log=False), 20.89)

    def test_current_price_hard_stop_when_market_below_avg_stop(self) -> None:
        raw, reason = calculate_raw_stop_price(avg_cost=100, market_price=90, stop_pct=0.05)
        self.assertAlmostEqual(raw, 85.5)
        self.assertIn("current-price hard stop", reason)

    def test_missing_stop_generates_repair_proposal(self) -> None:
        proposal = build_repair_preview_proposal(
            _guard_row(position_qty=10, protective_stop_qty=0),
            settings=_settings(),
            stop_pct=0.05,
        )
        self.assertEqual(proposal.proposed_order_type, "SELL STP LMT")
        self.assertEqual(proposal.recommended_order_type, "SELL STP LMT")
        self.assertEqual(proposal.proposed_qty, 10)
        self.assertEqual(proposal.recommended_qty, 10)
        self.assertEqual(proposal.proposed_stop_price, 104.5)
        self.assertIsNotNone(proposal.normalized_limit_price)
        self.assertTrue(proposal.outsideRth_requested)
        self.assertTrue(proposal.safe_to_repair)

    def test_underprotected_only_repairs_uncovered_qty(self) -> None:
        proposal = build_repair_preview_proposal(
            _guard_row(position_qty=10, protective_stop_qty=4),
            settings=_settings(),
            stop_pct=0.05,
        )
        self.assertEqual(proposal.uncovered_qty, 6)
        self.assertEqual(proposal.proposed_qty, 6)
        self.assertTrue(proposal.safe_to_repair)

    def test_fully_protected_generates_no_repair(self) -> None:
        proposal = build_repair_preview_proposal(
            _guard_row(position_qty=10, protective_stop_qty=10),
            settings=_settings(),
            stop_pct=0.05,
        )
        self.assertEqual(proposal.uncovered_qty, 0)
        self.assertFalse(proposal.safe_to_repair)
        self.assertIn("no uncovered quantity", proposal.reason)

    def test_overprotected_preview_requires_review(self) -> None:
        proposal = build_repair_preview_proposal(
            _guard_row(position_qty=10, protective_stop_qty=11),
            settings=_settings(),
            stop_pct=0.05,
        )
        self.assertTrue(proposal.overprotected_risk)
        self.assertFalse(proposal.safe_to_repair)

    def test_stop_price_at_or_above_current_price_is_rejected(self) -> None:
        with patch("trading.position_protection.normalize_order_price", return_value=110.0):
            proposal = build_repair_preview_proposal(
                _guard_row(position_qty=10, protective_stop_qty=0, bid=110, last=110),
                settings=_settings(),
                stop_pct=0.05,
            )
        self.assertTrue(proposal.would_trigger_immediately)
        self.assertFalse(proposal.safe_to_repair)

    def test_quote_stale_rejects_repair(self) -> None:
        proposal = build_repair_preview_proposal(
            _guard_row(position_qty=10, protective_stop_qty=0, quote_age_ms=20_001),
            settings=_settings(),
            stop_pct=0.05,
        )
        self.assertTrue(proposal.quote_stale)
        self.assertFalse(proposal.safe_to_repair)

    def test_duplicate_stop_marks_duplicate_risk(self) -> None:
        proposal = build_repair_preview_proposal(
            _guard_row(
                position_qty=10,
                protective_stop_qty=0,
                protective_stop_order_details=[
                    {
                        "action": "SELL",
                        "order_type": "STP",
                        "total_quantity": 10,
                        "aux_price": 104.5,
                    }
                ],
            ),
            settings=_settings(),
            stop_pct=0.05,
        )
        self.assertTrue(proposal.duplicate_risk)
        self.assertFalse(proposal.safe_to_repair)

    def test_preview_tick_rounding_for_sell_stop(self) -> None:
        proposal = build_repair_preview_proposal(
            _guard_row(position_qty=10, protective_stop_qty=0, bid=110.101, last=110.101),
            settings=_settings(),
            stop_pct=0.05,
        )
        self.assertEqual(proposal.proposed_stop_price, 104.59)

    def test_buy_freeze_does_not_block_sell_stop_protection(self) -> None:
        with patch.dict(os.environ, {"MODE9_BUY_FREEZE": "true"}):
            proposal = build_repair_preview_proposal(
                _guard_row(position_qty=10, protective_stop_qty=0),
                settings=_settings(),
                stop_pct=0.05,
            )
        self.assertEqual(proposal.proposed_action, "create_protective_sell_stop_limit")
        self.assertEqual(proposal.recommended_order_type, "SELL STP LMT")
        self.assertTrue(proposal.safe_to_repair)

    def test_atr_missing_falls_back_to_default_stop_pct(self) -> None:
        proposal = build_repair_preview_proposal(
            _guard_row(position_qty=10, protective_stop_qty=0, atr=None),
            settings=_settings(),
            stop_config=_stop_config(),
        )
        self.assertIsNone(proposal.atr_pct)
        self.assertEqual(proposal.stop_pct, 0.05)

    def test_low_atr_stop_pct_respects_minimum(self) -> None:
        proposal = build_repair_preview_proposal(
            _guard_row(position_qty=10, protective_stop_qty=0, atr=1.0, bid=100, ask=100.01, last=100),
            settings=_settings(),
            stop_config=_stop_config(),
        )
        self.assertEqual(proposal.stop_pct, 0.03)
        self.assertEqual(proposal.proposed_stop_price, 97.0)

    def test_high_atr_stock_stop_pct_widens(self) -> None:
        proposal = build_repair_preview_proposal(
            _guard_row(position_qty=10, protective_stop_qty=0, atr=5.0, bid=100, ask=100.01, last=100),
            settings=_settings(),
            stop_config=_stop_config(),
        )
        self.assertEqual(proposal.stop_pct, 0.075)
        self.assertEqual(proposal.proposed_stop_price, 92.5)

    def test_wide_spread_stop_pct_widens(self) -> None:
        proposal = build_repair_preview_proposal(
            _guard_row(position_qty=10, protective_stop_qty=0, atr=1.0, bid=100, ask=103, last=101),
            settings=_settings(),
            stop_config=_stop_config(),
        )
        self.assertEqual(proposal.spread_pct, 0.03)
        self.assertEqual(proposal.stop_pct, 0.09)

    def test_stop_pct_does_not_go_below_min(self) -> None:
        calc = calculate_dynamic_stop(reference_price=100, bid=100, ask=100, atr=0.01, config=_stop_config())
        self.assertEqual(calc["stop_pct"], 0.03)

    def test_stop_pct_does_not_go_above_max(self) -> None:
        calc = calculate_dynamic_stop(reference_price=100, bid=100, ask=100, atr=20, config=_stop_config())
        self.assertEqual(calc["stop_pct"], 0.12)

    def test_position_stop_stale_ms_rejects_repair(self) -> None:
        proposal = build_repair_preview_proposal(
            _guard_row(position_qty=10, protective_stop_qty=0, quote_age_ms=5_001),
            settings=_settings(),
            stop_config=_stop_config(),
        )
        self.assertTrue(proposal.quote_stale)
        self.assertFalse(proposal.safe_to_repair)

    def test_average_cost_and_pnl_enter_preview(self) -> None:
        proposal = build_repair_preview_proposal(
            _guard_row(position_qty=10, protective_stop_qty=0, bid=110, last=110, avg_cost=100),
            settings=_settings(),
            stop_config=_stop_config(),
        )
        self.assertEqual(proposal.average_cost, 100)
        self.assertEqual(proposal.unrealized_pnl_pct, 10.0)
        self.assertEqual(proposal.estimated_pnl_if_stop_triggered, 45.0)

    def test_large_unrealized_loss_requires_manual_review(self) -> None:
        proposal = build_repair_preview_proposal(
            _guard_row(position_qty=10, protective_stop_qty=0, bid=89, last=89, avg_cost=100),
            settings=_settings(),
            stop_config=_stop_config(),
        )
        self.assertTrue(proposal.manual_review_required)
        self.assertFalse(proposal.safe_to_repair)

    def test_strategy_debt_document_exists(self) -> None:
        doc = Path("docs/STRATEGY_DEBT.md")
        self.assertTrue(doc.exists())
        text = doc.read_text(encoding="utf-8")
        self.assertIn("STOP-001", text)
        self.assertIn("STOP-007", text)

    def test_dry_run_preview_contains_strategy_debt_ids(self) -> None:
        report = build_repair_preview_report(
            settings=_settings(),
            guard_report={"symbols": [_guard_row(position_qty=10, protective_stop_qty=0)]},
            stop_config=_stop_config(),
        )
        self.assertIn("STOP-001", report["strategy_debt_ids"])
        self.assertIn("STOP-001", report["proposals"][0]["strategy_debt_ids"])

    def test_auto_test_symbol_selection_is_deterministic_lowest_uncovered_notional(self) -> None:
        report = build_repair_preview_report(
            settings=_settings(),
            guard_report={
                "symbols": [
                    _guard_row(symbol="AAPL", position_qty=10, protective_stop_qty=0, bid=110, last=110),
                    _guard_row(symbol="T", position_qty=5, protective_stop_qty=2, bid=21, ask=21.01, last=21, avg_cost=21),
                    _guard_row(symbol="NIO", position_qty=200, protective_stop_qty=0, bid=4.8, ask=4.81, last=4.8, avg_cost=5),
                ]
            },
            stop_config=_stop_config(),
        )
        selected = report["test_then_bulk"]
        self.assertEqual(selected["selected_test_symbol"], "T")
        self.assertEqual(selected["uncovered_qty"], 3)
        self.assertEqual(selected["uncovered_notional"], 63.0)
        self.assertEqual([item["symbol"] for item in selected["eligible_test_symbols"]], ["T", "NIO", "AAPL"])

    def test_manual_test_symbol_t_selects_only_t(self) -> None:
        report = build_repair_preview_report(
            settings=_settings(),
            guard_report={
                "symbols": [
                    _guard_row(symbol="AAPL", position_qty=10, protective_stop_qty=0, bid=110, last=110),
                    _guard_row(symbol="T", position_qty=5, protective_stop_qty=2, bid=21, ask=21.01, last=21, avg_cost=21),
                ]
            },
            stop_config=_stop_config(),
        )
        selected = select_test_then_bulk_symbol(
            report["proposals"],
            test_symbol="T",
            test_order_limit=1,
        )
        self.assertEqual(selected.selected_test_symbol, "T")
        self.assertEqual(selected.uncovered_qty, 3)
        self.assertIn("manual POSITION_PROTECTION_TEST_SYMBOL=T passed", selected.selected_reason)

    def test_manual_test_symbol_rejects_missing_or_unsafe_symbol(self) -> None:
        report = build_repair_preview_report(
            settings=_settings(),
            guard_report={"symbols": [_guard_row(symbol="T", position_qty=5, protective_stop_qty=5)]},
            stop_config=_stop_config(),
        )
        missing = select_test_then_bulk_symbol(report["proposals"], test_symbol="MSFT", test_order_limit=1)
        self.assertIsNone(missing.selected_test_symbol)
        self.assertIn("does not exist", missing.selected_reason)
        unsafe = select_test_then_bulk_symbol(report["proposals"], test_symbol="T", test_order_limit=1)
        self.assertIsNone(unsafe.selected_test_symbol)
        self.assertIn("uncovered_qty<=0", unsafe.selected_reason)

    @patch("trading.position_protection.require_fresh_state_for_execution")
    @patch("trading.position_protection.read_lock")
    @patch("trading.position_protection.TwsPaperBroker")
    def test_test_order_limit_one_limits_orders_not_shares(self, broker_class, read_lock, force_refresh) -> None:
        read_lock.return_value = {"process_name": "mode9_autonomous_agent"}
        force_refresh.return_value = self._fresh_ok()
        confirmation = type("Confirmation", (), {"order_ids": [123], "statuses": {123: "PreSubmitted"}, "open_order_states": {123: "PreSubmitted"}})()
        broker_class.return_value.submit_stop.return_value = confirmation
        with tempfile.TemporaryDirectory() as tmp, patch("trading.position_protection.REPORT_DIR", Path(tmp)), patch.dict(
            os.environ,
            {
                "POSITION_PROTECTION_TEST_SYMBOL": "T",
                "POSITION_PROTECTION_TEST_ORDER_LIMIT": "1",
            },
        ):
            report = run_position_protection(
                settings=_settings(),
                enabled=True,
                guard_report={
                    "symbols": [
                        _guard_row(symbol="AAPL", position_qty=10, protective_stop_qty=0, bid=110, last=110),
                        _guard_row(symbol="T", position_qty=5, protective_stop_qty=2, bid=21, ask=21.01, last=21, avg_cost=21),
                    ]
                },
            )
        self.assertEqual(report["submitted_count"], 1)
        broker_class.return_value.submit_stop.assert_called_once()
        self.assertEqual(broker_class.return_value.submit_stop.call_args.kwargs["symbol"], "T")
        self.assertEqual(broker_class.return_value.submit_stop.call_args.kwargs["quantity"], 3)
        self.assertEqual(broker_class.return_value.submit_stop.call_args.kwargs["action"], "SELL")
        self.assertTrue(broker_class.return_value.submit_stop.call_args.kwargs["outside_rth"])
        submitted = report["submitted_protection_orders"][0]
        self.assertEqual(submitted["tif"], "GTC")
        self.assertEqual(submitted["order_type"], "STP")
        self.assertTrue(submitted["order_ref"])

    @patch("trading.position_protection.require_fresh_state_for_execution")
    @patch("trading.position_protection.read_lock")
    @patch("trading.position_protection.TwsPaperBroker")
    def test_test_mode_writes_success_result(self, broker_class, read_lock, force_refresh) -> None:
        read_lock.return_value = {"process_name": "mode9_autonomous_agent"}
        force_refresh.return_value = self._fresh_ok()
        confirmation = type("Confirmation", (), {"order_ids": [123], "statuses": {123: "PreSubmitted"}, "open_order_states": {123: "PreSubmitted"}})()
        broker_class.return_value.submit_stop.return_value = confirmation
        with tempfile.TemporaryDirectory() as tmp, patch("trading.position_protection.REPORT_DIR", Path(tmp)), patch.dict(
            os.environ,
            {
                "POSITION_PROTECTION_REPAIR_MODE": "test",
                "POSITION_PROTECTION_TEST_SYMBOL": "T",
                "POSITION_PROTECTION_TEST_ORDER_LIMIT": "1",
            },
        ):
            report = run_position_protection(
                settings=_settings(),
                enabled=True,
                guard_report={"symbols": [_guard_row(symbol="T", position_qty=5, protective_stop_qty=2, bid=21, ask=21.01, last=21, avg_cost=21)]},
            )
            result = __import__("json").loads((Path(tmp) / "test_repair_result.json").read_text())
            self.assertTrue((Path(tmp) / "test_repair_result.md").exists())
        self.assertEqual(report["paper_operation_mode"], "repair_test")
        self.assertTrue(result["success"])
        self.assertEqual(result["symbol"], "T")
        self.assertEqual(result["qty"], 3)

    @patch("trading.position_protection.require_fresh_state_for_execution")
    @patch("trading.position_protection.read_lock")
    @patch("trading.position_protection.TwsPaperBroker")
    def test_force_refresh_failure_blocks_repair_submission(self, broker_class, read_lock, force_refresh) -> None:
        read_lock.return_value = {"process_name": "mode9_autonomous_agent"}
        force_refresh.return_value = ForceRefreshResult(True, True, False, True, True, False, False, True, "quote stale after force refresh")
        with patch.dict(
            os.environ,
            {
                "POSITION_PROTECTION_REPAIR_MODE": "test",
                "POSITION_PROTECTION_TEST_SYMBOL": "T",
                "POSITION_PROTECTION_TEST_ORDER_LIMIT": "1",
            },
        ):
            report = run_position_protection(
                settings=_settings(),
                enabled=True,
                guard_report={"symbols": [_guard_row(symbol="T", position_qty=5, protective_stop_qty=2, bid=21, ask=21.01, last=21, avg_cost=21)]},
            )

        self.assertEqual(report["submitted_count"], 0)
        broker_class.return_value.submit_stop.assert_not_called()
        self.assertIn("quote stale after force refresh", report["records"][0]["blocked_reason"])
        self.assertTrue(report["records"][0]["force_refresh_required"])
        self.assertFalse(report["records"][0]["force_refresh_ok"])

    @patch("trading.position_protection.latest_test_repair_result", return_value={"success": True})
    @patch("trading.position_protection.require_fresh_state_for_execution")
    @patch("trading.position_protection.read_lock")
    @patch("trading.position_protection.TwsPaperBroker")
    def test_run_mode_repairs_all_safe_symbols(self, broker_class, read_lock, force_refresh, _latest) -> None:
        read_lock.return_value = {"process_name": "mode9_autonomous_agent"}
        force_refresh.return_value = self._fresh_ok()
        broker_class.return_value.submit_stop.return_value = type("Confirmation", (), {"order_ids": [123], "statuses": {123: "PreSubmitted"}, "open_order_states": {123: "PreSubmitted"}})()
        with patch.dict(os.environ, {"POSITION_PROTECTION_REPAIR_MODE": "run", "POSITION_PROTECTION_TEST_ORDER_LIMIT": "1", "POSITION_PROTECTION_RUN_MAX_ORDERS": "20"}):
            report = run_position_protection(
                settings=_settings(),
                enabled=True,
                guard_report={
                    "symbols": [
                        _guard_row(symbol="AAPL", position_qty=10, protective_stop_qty=0, bid=110, last=110),
                        _guard_row(symbol="T", position_qty=5, protective_stop_qty=2, bid=21, ask=21.01, last=21, avg_cost=21),
                        _guard_row(symbol="PFE", position_qty=9, protective_stop_qty=1, bid=24, ask=24.01, last=24, avg_cost=24),
                    ]
                },
            )
        self.assertEqual(report["paper_operation_mode"], "paper_protection_run")
        self.assertEqual(report["submitted_count"], 3)
        self.assertEqual(broker_class.return_value.submit_stop.call_count, 3)

    @patch("trading.position_protection.latest_test_repair_result", return_value={"success": True})
    @patch("trading.position_protection.require_fresh_state_for_execution")
    @patch("trading.position_protection.read_lock")
    @patch("trading.position_protection.TwsPaperBroker")
    def test_run_mode_skips_manual_review_symbols(self, broker_class, read_lock, force_refresh, _latest) -> None:
        read_lock.return_value = {"process_name": "mode9_autonomous_agent"}
        force_refresh.return_value = self._fresh_ok()
        broker_class.return_value.submit_stop.return_value = type("Confirmation", (), {"order_ids": [123], "statuses": {123: "PreSubmitted"}, "open_order_states": {123: "PreSubmitted"}})()
        with patch.dict(os.environ, {"POSITION_PROTECTION_REPAIR_MODE": "run", "POSITION_PROTECTION_RUN_MAX_ORDERS": "20"}):
            report = run_position_protection(
                settings=_settings(),
                enabled=True,
                guard_report={
                    "symbols": [
                        _guard_row(symbol="AAPL", position_qty=10, protective_stop_qty=0, bid=110, last=110),
                        _guard_row(symbol="LOSS", position_qty=10, protective_stop_qty=0, bid=80, last=80, avg_cost=100),
                    ]
                },
            )
        self.assertEqual(report["submitted_count"], 1)
        self.assertEqual(report["submitted_protection_orders"][0]["symbol"], "AAPL")

    @patch("trading.position_protection.latest_test_repair_result", return_value={"success": True})
    @patch("trading.position_protection.require_fresh_state_for_execution")
    @patch("trading.position_protection.read_lock")
    @patch("trading.position_protection.TwsPaperBroker")
    def test_run_mode_respects_run_max_orders(self, broker_class, read_lock, force_refresh, _latest) -> None:
        read_lock.return_value = {"process_name": "mode9_autonomous_agent"}
        force_refresh.return_value = self._fresh_ok()
        broker_class.return_value.submit_stop.return_value = type("Confirmation", (), {"order_ids": [123], "statuses": {123: "PreSubmitted"}, "open_order_states": {123: "PreSubmitted"}})()
        with patch.dict(os.environ, {"POSITION_PROTECTION_REPAIR_MODE": "run", "POSITION_PROTECTION_RUN_MAX_ORDERS": "2", "POSITION_PROTECTION_TEST_ORDER_LIMIT": "1"}):
            report = run_position_protection(
                settings=_settings(),
                enabled=True,
                guard_report={
                    "symbols": [
                        _guard_row(symbol="AAPL", position_qty=10, protective_stop_qty=0, bid=110, last=110),
                        _guard_row(symbol="MSFT", position_qty=10, protective_stop_qty=0, bid=210, last=210, avg_cost=200),
                        _guard_row(symbol="PFE", position_qty=10, protective_stop_qty=0, bid=24, last=24, avg_cost=24),
                    ]
                },
            )
        self.assertEqual(report["submitted_count"], 2)

    @patch("trading.position_protection.latest_test_repair_result", return_value={})
    @patch("trading.position_protection.read_lock")
    @patch("trading.position_protection.TwsPaperBroker")
    def test_run_mode_requires_test_success_when_configured(self, broker_class, read_lock, _latest) -> None:
        read_lock.return_value = {"process_name": "mode9_autonomous_agent"}
        with patch.dict(os.environ, {"POSITION_PROTECTION_REPAIR_MODE": "run", "POSITION_PROTECTION_RUN_REQUIRE_TEST_SUCCESS": "true"}):
            report = run_position_protection(
                settings=_settings(),
                enabled=True,
                guard_report={"symbols": [_guard_row(symbol="AAPL", position_qty=10, protective_stop_qty=0, bid=110, last=110)]},
            )
        self.assertEqual(report["submitted_count"], 0)
        self.assertFalse(report["run_allowed"])
        self.assertIn("latest test repair success is not true", report["run_blocked_reason"])
        broker_class.assert_not_called()

    @patch("trading.position_protection.read_lock")
    @patch("trading.position_protection.TwsPaperBroker")
    def test_repair_requires_mode9_execution_lock(self, broker_class, read_lock) -> None:
        read_lock.return_value = None
        settings = _settings()
        guard = {
            "symbols": [
                {
                    "symbol": "AAPL",
                    "position_qty": 10,
                    "avg_cost": 100,
                    "market_price": 110,
                    "bid": 110,
                    "ask": 110.02,
                    "last": 110,
                    "quote_age_ms": 100,
                    "protective_stop_qty": 0,
                    "stale_quote_warning": False,
                    "spread_warning": False,
                }
            ]
        }
        report = run_position_protection(settings=settings, enabled=True, guard_report=guard)
        self.assertEqual(report["submitted_count"], 0)
        self.assertIn("execution-writer lock", report["records"][0]["blocked_reason"])
        broker_class.assert_not_called()


def _settings():
    from trading.config import Settings

    return Settings(
        api_key="key",
        api_host="127.0.0.1",
        api_port=8787,
        trading_mode="PAPER",
        allow_tws_staging=True,
        allow_paper_transmit=True,
        allow_outside_rth=True,
        trading_kill_switch=False,
        trade_session_token="token",
        tws_host="127.0.0.1",
        tws_port=7497,
        tws_client_id=22,
        tws_status_timeout=1,
        allowed_symbols=frozenset({"AAPL"}),
        max_quantity=1,
        max_order_value=400,
        max_risk_per_order=10,
        max_daily_notional_value=None,
        daily_notional_timezone="Europe/Berlin",
        streaming_market_data_enabled=False,
        streaming_symbols=(),
        streaming_max_symbols=3,
        streaming_stale_ms=3000,
        streaming_tws_host="127.0.0.1",
        streaming_tws_port=7497,
        streaming_client_id=32,
        audit_db=__import__("pathlib").Path(":memory:"),
    )


def _guard_row(
    *,
    symbol: str = "AAPL",
    position_qty: float,
    protective_stop_qty: float,
    bid: float = 110,
    ask: float = 110.02,
    last: float = 110,
    avg_cost: float = 100,
    atr: float | None = None,
    quote_age_ms: float = 100,
    protective_stop_order_details: list[dict] | None = None,
) -> dict:
    return {
        "symbol": symbol,
        "position_qty": position_qty,
        "avg_cost": avg_cost,
        "market_price": last,
        "bid": bid,
        "ask": ask,
        "last": last,
        "atr": atr,
        "quote_age_ms": quote_age_ms,
        "protective_stop_qty": protective_stop_qty,
        "protective_stop_order_details": protective_stop_order_details or [],
        "stale_quote_warning": quote_age_ms > 10_000,
        "spread_warning": False,
    }


def _stop_config() -> StopConfig:
    return StopConfig(
        mode="dynamic",
        default_pct=0.05,
        min_pct=0.03,
        max_pct=0.12,
        atr_multiplier=1.5,
        spread_multiplier=3.0,
        stale_ms=5_000,
        require_fresh_quote=True,
        repair_max_per_cycle=10,
    )


if __name__ == "__main__":
    unittest.main()
