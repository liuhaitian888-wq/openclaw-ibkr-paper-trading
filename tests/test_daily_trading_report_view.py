import json
import os
import unittest
from unittest.mock import patch

from scripts.daily_trading_report_view import (
    build_daily_report_view,
    compact_blockers,
    render_daily_report_feishu,
    render_daily_report_markdown,
)
from scripts.send_feishu_report import build_post_payload, require_target


def sample_report(*, lifecycle: str = "MARKET_CLOSED_WAITING", coverage: object | None = None, daily_pnl: object = "MISSING") -> dict:
    if coverage is None:
        coverage = [
            {"symbol": "AAPL", "position_qty": 1, "existing_stop_qty": 0, "uncovered_qty": 1, "covered": False},
            {"symbol": "MSFT", "position_qty": 1, "existing_stop_qty": 1, "uncovered_qty": 0, "covered": True},
        ]
    daily_freshness = "MISSING" if daily_pnl == "MISSING" else "FRESH"
    return {
        "date_utc": "2026-09-04",
        "runtime": {
            "lifecycle_state": lifecycle,
            "market_session_state": "CLOSED" if lifecycle == "MARKET_CLOSED_WAITING" else "RTH",
            "ibkr_connected": True,
            "execution_enabled": lifecycle == "PAPER_READY",
            "mode9_running": lifecycle in {"PAPER_READY", "SAFE_MODE", "MARKET_CLOSED_WAITING"},
            "blocked_reason": "market_closed_no_live_bid_ask_expected" if lifecycle == "MARKET_CLOSED_WAITING" else "",
        },
        "data_quality": {
            "account_execution_ready": lifecycle == "PAPER_READY",
            "quotes_ready": lifecycle == "PAPER_READY",
            "positions_ready": True,
            "open_orders_ready": True,
            "pnl_ready": True,
            "protection_coverage_ready": bool(coverage),
            "blocking_reasons": ["EXECUTION_GATE blocks SELL execution because bid is missing or has no age"],
        },
        "account_snapshot": {
            "account_id": {"value": "DU...49", "freshness": "FRESH"},
            "net_liquidation": {"value": 1000, "freshness": "FRESH"},
            "total_cash_value": {"value": 500, "freshness": "FRESH"},
            "buying_power": {"value": 2000, "freshness": "FRESH"},
            "available_funds": {"value": 700, "freshness": "FRESH"},
            "daily_pnl": {"value": daily_pnl, "freshness": daily_freshness},
            "realized_pnl": {"value": 0.0, "freshness": "FRESH"},
            "unrealized_pnl": {"value": 12.5, "freshness": "FRESH"},
            "gross_exposure": {"value": 250, "freshness": "FRESH"},
            "positions": [
                {"symbol": "AAPL", "quantity": 1, "market_value": 100},
                {"symbol": "MSFT", "quantity": 1, "market_value": 150},
            ],
            "protective_order_coverage": coverage,
            "data_quality": {
                "protection_coverage_fresh": bool(coverage),
            },
        },
        "lifecycle_funnel": {
            "strategy_decisions": 0,
            "order_intents": 3,
            "risk_rejected": 0,
            "submitted": 0,
            "broker_ack": 0,
            "partial_fill": 0,
            "filled": 0,
            "executions": 0,
            "commissions": 0,
        },
    }


class DailyTradingReportViewTests(unittest.TestCase):
    def test_builds_qa_view_model_and_markdown(self) -> None:
        view = build_daily_report_view(sample_report())
        text = render_daily_report_markdown(sample_report())

        self.assertEqual(view.title, "买 der · Paper Trading 日报")
        self.assertIn("Q：今天系统正常吗？", text)
        self.assertIn("状态：MARKET_CLOSED_WAITING", text)

    def test_feishu_renderer_uses_same_qa_shape(self) -> None:
        text = render_daily_report_feishu(sample_report(), test=True)
        payload = build_post_payload("【测试】买 der · Paper Trading 日报", text)

        self.assertIn("【测试】买 der · Paper Trading 日报", text)
        self.assertEqual(payload["msg_type"], "post")
        self.assertIn("Q：今天下单了吗？", text)

    def test_missing_daily_pnl_is_not_rendered_as_zero(self) -> None:
        text = render_daily_report_markdown(sample_report(daily_pnl="MISSING"))

        self.assertIn("DailyPnL 暂缺（MISSING）", text)
        self.assertNotIn("DailyPnL 0.00", text)

    def test_market_closed_explanation_is_not_a_fault(self) -> None:
        text = render_daily_report_markdown(sample_report(lifecycle="MARKET_CLOSED_WAITING"))

        self.assertIn("美国市场已收盘", text)
        self.assertIn("目前不视为行情故障", text)
        self.assertIn("outside_session_no_quote", text)

    def test_rth_missing_l1_is_rendered_as_abnormal(self) -> None:
        text = render_daily_report_markdown(sample_report(lifecycle="SAFE_MODE"))

        self.assertIn("异常。当前处于交易时段", text)

    def test_missing_protection_is_unknown_not_uncovered(self) -> None:
        text = render_daily_report_markdown(sample_report(coverage=[]))
        protection_answer = text.split("Q：这些仓位都有保护吗？", 1)[1].split("Q：实时行情正常吗？", 1)[0]

        self.assertIn("protection data = MISSING", protection_answer)
        self.assertNotIn("0/2", protection_answer)

    def test_paper_ready_blockers_are_compressed(self) -> None:
        report = sample_report()
        report["data_quality"]["blocking_reasons"] = ["one", "two", "three", "four", "five"]

        text = render_daily_report_markdown(report)

        self.assertIn("当前主要 blocker", text)
        self.assertLessEqual(text.count("；"), 12)

    def test_account_id_is_not_leaked(self) -> None:
        text = json.dumps(build_daily_report_view(sample_report()).__dict__, ensure_ascii=False)

        self.assertNotIn("DUQ503649", text)

    def test_compact_blockers_deduplicates_long_lists(self) -> None:
        blockers = compact_blockers(["quotes missing", "quotes missing", "market_closed_no_live_bid_ask_expected"], limit=2)

        self.assertEqual(len(blockers), 2)

    def test_require_target_blocks_unconfirmed_deehub(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit):
                require_target("deehub")

    def test_require_target_accepts_deehub(self) -> None:
        with patch.dict(os.environ, {"FEISHU_TARGET_NAME": "deehub"}, clear=True):
            require_target("deehub")


if __name__ == "__main__":
    unittest.main()
