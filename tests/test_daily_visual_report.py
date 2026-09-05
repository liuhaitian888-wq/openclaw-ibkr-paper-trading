import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.daily_visual_report import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    build_visual_report_view_model,
    html_document,
    png_dimensions,
    render_html,
    validate_manifest_consistency,
    visual_manifest,
    write_manifest,
)
from scripts.send_feishu_report import (
    build_image_payload,
    feishu_image_capability,
    sanitize_text,
    tenant_access_token,
    upload_image,
)
from scripts.send_daily_visual_feishu_update import send_daily_visual_update


def sample_report(*, daily_pnl=0.0, daily_freshness="FRESH", coverage=None, lifecycle="PAPER_READY"):
    if coverage is None:
        coverage = [
            {"symbol": "AAPL", "position_qty": 2, "existing_stop_qty": 2, "uncovered_qty": 0, "covered": True},
            {"symbol": "PFE", "position_qty": 8, "existing_stop_qty": 0, "uncovered_qty": 8, "covered": False},
        ]
    return {
        "timestamp": "2026-09-04T05:55:29+00:00",
        "date_utc": "2026-09-04",
        "trading_date": "2026-09-03",
        "runtime": {
            "lifecycle_state": lifecycle,
            "market_session_state": "CLOSED" if lifecycle == "MARKET_CLOSED_WAITING" else "RTH",
            "execution_enabled": lifecycle == "PAPER_READY",
        },
        "data_quality": {
            "account_execution_ready": lifecycle == "PAPER_READY",
            "quotes_ready": lifecycle == "PAPER_READY",
            "blocking_reasons": ["one", "two", "three", "four"],
        },
        "account_snapshot": {
            "account_id": {"value": "DU...49", "freshness": "FRESH"},
            "net_liquidation": {"value": 1000.0, "freshness": "FRESH"},
            "total_cash_value": {"value": 800.0, "freshness": "FRESH"},
            "buying_power": {"value": 2000.0, "freshness": "FRESH"},
            "available_funds": {"value": 700.0, "freshness": "FRESH"},
            "daily_pnl": {"value": daily_pnl, "freshness": daily_freshness},
            "realized_pnl": {"value": 0.0, "freshness": "FRESH"},
            "unrealized_pnl": {"value": 12.34, "freshness": "FRESH"},
            "gross_exposure": {"value": 450.0, "freshness": "FRESH"},
            "net_exposure": {"value": 450.0, "freshness": "FRESH"},
            "open_orders": [],
            "positions": [
                {"symbol": "AAPL", "quantity": 2, "market_value": 200},
                {"symbol": "PFE", "quantity": 8, "market_value": 250},
            ],
            "protective_order_coverage": coverage,
            "data_quality": {"protection_coverage_fresh": True},
        },
        "lifecycle_funnel": {
            "submitted": 0,
            "executions": 0,
            "filled": 0,
        },
    }


def png_bytes(width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT):
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + width.to_bytes(4, "big") + height.to_bytes(4, "big") + b"\x08\x02\x00\x00\x00"


class FakeHTTPResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        if isinstance(self.payload, bytes):
            return self.payload
        return json.dumps(self.payload).encode("utf-8")


class DailyVisualReportTests(unittest.TestCase):
    def test_daily_report_to_visual_view_model(self):
        vm = build_visual_report_view_model(sample_report())

        self.assertEqual(vm.trading_date, "2026-09-03")
        self.assertEqual(vm.paper_ready, "YES")
        self.assertEqual(vm.net_liquidation, "1,000.00")

    def test_missing_pnl_renders_missing(self):
        vm = build_visual_report_view_model(sample_report(daily_pnl="MISSING", daily_freshness="MISSING"))

        self.assertEqual(vm.daily_pnl, "MISSING")

    def test_real_zero_renders_zero(self):
        vm = build_visual_report_view_model(sample_report(daily_pnl=0.0))

        self.assertEqual(vm.daily_pnl, "0.00")

    def test_protection_unknown_is_not_unprotected(self):
        report = sample_report(coverage=[])
        vm = build_visual_report_view_model(report)

        self.assertEqual(vm.protection_status, "UNKNOWN")
        self.assertNotEqual(vm.protection_status, "UNPROTECTED")

    def test_market_closed_l1_is_expected(self):
        vm = build_visual_report_view_model(sample_report(lifecycle="MARKET_CLOSED_WAITING"))

        self.assertEqual(vm.l1_status, "EXPECTED")
        self.assertIn("Market closed", vm.l1_text)

    def test_rth_missing_l1_is_error(self):
        vm = build_visual_report_view_model(sample_report(lifecycle="SAFE_MODE"))

        self.assertEqual(vm.l1_status, "ERROR")

    def test_paper_ready_rendering_and_blocker_compression(self):
        vm = build_visual_report_view_model(sample_report(lifecycle="SAFE_MODE"))

        self.assertEqual(vm.paper_ready, "NO")
        self.assertLessEqual(len(vm.blockers), 3)

    def test_long_text_overflow_and_unicode_rendering(self):
        report = sample_report(lifecycle="SAFE_MODE")
        report["data_quality"]["blocking_reasons"] = ["中文 blocker " + "x" * 500]
        text = render_html(report)

        self.assertIn("买 der", text)
        self.assertIn("中文 blocker", text)
        self.assertLess(len(text), 20000)

    def test_7_day_chart_missing_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            vm = build_visual_report_view_model(sample_report(), history_dir=Path(tmp))

        self.assertFalse(vm.chart_available)

    def test_html_generation(self):
        text = render_html(sample_report())

        self.assertIn("<!doctype html>", text)
        self.assertIn("Net Liquidation", text)
        self.assertIn("PAPER_READY", text)

    def test_png_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.png"
            path.write_bytes(png_bytes())

            self.assertEqual(png_dimensions(path), (DEFAULT_WIDTH, DEFAULT_HEIGHT))

    def test_manifest_consistency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "latest.json"
            html_path = root / "latest.html"
            png_path = root / "latest.png"
            report = sample_report()
            report_path.write_text(json.dumps(report), encoding="utf-8")
            html_path.write_text(html_document(build_visual_report_view_model(report, history_dir=root)), encoding="utf-8")
            png_path.write_bytes(png_bytes())
            vm = build_visual_report_view_model(report, history_dir=root)
            manifest = visual_manifest(report_path, html_path, png_path, report, vm, width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT)

            validate_manifest_consistency(manifest, report, vm)
            write_manifest(root, manifest, vm.trading_date)
            self.assertTrue((root / "visual_report_manifest.json").exists())

    def test_feishu_image_sender_mock(self):
        self.assertEqual(build_image_payload("img_v2_key")["msg_type"], "image")

    def test_image_capability_blocks_without_upload_credentials(self):
        with patch.dict("os.environ", {"FEISHU_WEBHOOK_URL": "https://example.invalid"}, clear=True):
            cap = feishu_image_capability()

        self.assertFalse(cap["ready"])
        self.assertIn("missing", cap["blocked_reason"])

    def test_image_upload_uses_existing_image_key_without_upload(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"FEISHU_IMAGE_KEY": "img_v2_key"}, clear=True):
            path = Path(tmp) / "x.png"
            path.write_bytes(png_bytes())

            self.assertEqual(upload_image(path), "img_v2_key")

    def test_token_success_from_app_credentials(self):
        payload = {"code": 0, "tenant_access_token": "tenant-token"}
        with patch.dict("os.environ", {"FEISHU_APP_ID": "app-id", "FEISHU_APP_SECRET": "app-secret"}, clear=True), patch(
            "urllib.request.urlopen", return_value=FakeHTTPResponse(payload)
        ):
            self.assertEqual(tenant_access_token(), "tenant-token")

    def test_token_failure_is_reported_without_secret(self):
        payload = {"code": 999, "msg": "bad credential"}
        with patch.dict("os.environ", {"FEISHU_APP_ID": "app-id", "FEISHU_APP_SECRET": "app-secret"}, clear=True), patch(
            "urllib.request.urlopen", return_value=FakeHTTPResponse(payload)
        ):
            with self.assertRaises(RuntimeError) as raised:
                tenant_access_token()

        self.assertIn("code=999", str(raised.exception))
        self.assertNotIn("app-secret", str(raised.exception))

    def test_png_upload_success_and_image_key_parsing(self):
        payload = {"code": 0, "data": {"image_key": "img_v2_daily"}}
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"FEISHU_TENANT_ACCESS_TOKEN": "tenant-token"}, clear=True), patch(
            "urllib.request.urlopen", return_value=FakeHTTPResponse(payload)
        ):
            path = Path(tmp) / "latest.png"
            path.write_bytes(png_bytes())

            self.assertEqual(upload_image(path), "img_v2_daily")

    def test_deehub_image_send_success(self):
        manifest = {
            "image_path": "/tmp/latest.png",
            "html_path": "/tmp/latest.html",
            "image_size": 123,
            "image_width": DEFAULT_WIDTH,
            "image_height": DEFAULT_HEIGHT,
        }
        sent_payloads = []

        def capture_payload(payload):
            sent_payloads.append(payload)
            return '{"code":0,"msg":"success"}'

        with tempfile.TemporaryDirectory() as tmp, patch("scripts.send_daily_visual_feishu_update.load_env_file"), patch(
            "scripts.send_daily_visual_feishu_update.require_target"
        ), patch("scripts.send_daily_visual_feishu_update.write_local_qa_markdown", return_value=Path(tmp) / "latest.md"), patch(
            "scripts.send_daily_visual_feishu_update.write_visual_report", return_value=manifest
        ), patch(
            "scripts.send_daily_visual_feishu_update.feishu_image_capability", return_value={"ready": True}
        ), patch(
            "scripts.send_daily_visual_feishu_update.upload_image", return_value="img_v2_daily"
        ), patch(
            "scripts.send_daily_visual_feishu_update.send_webhook_payload", side_effect=capture_payload
        ):
            result = send_daily_visual_update(output_dir=Path(tmp))

        self.assertEqual(result["status"], "sent")
        self.assertEqual(sent_payloads, [{"msg_type": "image", "content": {"image_key": "img_v2_daily"}}])

    def test_image_failure_sends_short_error_notification_only(self):
        manifest = {
            "image_path": "/tmp/latest.png",
            "html_path": "/tmp/latest.html",
            "image_size": 123,
            "image_width": DEFAULT_WIDTH,
            "image_height": DEFAULT_HEIGHT,
        }
        sent_payloads = []

        def capture_payload(payload):
            sent_payloads.append(payload)
            return '{"code":0,"msg":"success"}'

        with tempfile.TemporaryDirectory() as tmp, patch("scripts.send_daily_visual_feishu_update.load_env_file"), patch(
            "scripts.send_daily_visual_feishu_update.require_target"
        ), patch("scripts.send_daily_visual_feishu_update.write_local_qa_markdown", return_value=Path(tmp) / "latest.md"), patch(
            "scripts.send_daily_visual_feishu_update.write_visual_report", return_value=manifest
        ), patch(
            "scripts.send_daily_visual_feishu_update.feishu_image_capability",
            return_value={"ready": False, "blocked_reason": "missing Feishu image upload credentials or FEISHU_IMAGE_KEY"},
        ), patch(
            "scripts.send_daily_visual_feishu_update.send_webhook_payload", side_effect=capture_payload
        ):
            result = send_daily_visual_update(output_dir=Path(tmp))

        self.assertEqual(result["status"], "image_failed")
        self.assertTrue(result["failure_notification_sent"])
        self.assertEqual(len(sent_payloads), 1)
        self.assertEqual(sent_payloads[0]["msg_type"], "text")
        self.assertIn("买 der 日报图片发送失败", sent_payloads[0]["content"]["text"])
        self.assertNotIn("今天系统正常吗", sent_payloads[0]["content"]["text"])

    def test_account_id_sanitization(self):
        text = render_html(sample_report())

        self.assertIn("DU...49", text)
        self.assertNotIn("DUQ503649", text)

    def test_no_secret_leakage(self):
        text = render_html(sample_report())

        self.assertNotIn("FEISHU_WEBHOOK_SECRET", text)
        self.assertNotIn("open-apis/bot/v2/hook", text)

    def test_sanitizes_feishu_webhook_in_errors(self):
        text = sanitize_text("failed https://open.feishu.cn/open-apis/bot/v2/hook/abcdef-secret-token")

        self.assertIn("[redacted-feishu-webhook]", text)
        self.assertNotIn("abcdef-secret-token", text)

    def test_daily_command_sends_only_visual_report(self):
        command = (Path(__file__).resolve().parents[1] / "scripts" / "send_daily_feishu_update.command").read_text(encoding="utf-8")

        self.assertIn("scripts/send_daily_visual_feishu_update.py", command)
        self.assertNotIn("generate_daily_feishu_update.py", command)
        self.assertNotIn("scripts/send_feishu_report.py \"$REPORT_PATH\"", command)
        self.assertNotIn("--msg-type image || true", command)

    def test_if_due_marks_sent_only_after_visual_success(self):
        command = (Path(__file__).resolve().parents[1] / "scripts" / "send_daily_feishu_update_if_due.command").read_text(encoding="utf-8")
        send_index = command.index("if scripts/send_daily_feishu_update.command")
        mark_index = command.index("mark-sent")
        fail_index = command.index("not marking sent")

        self.assertLess(send_index, mark_index)
        self.assertLess(mark_index, fail_index)

    def test_configure_script_accepts_image_upload_credentials_without_fixed_image_key(self):
        command = (Path(__file__).resolve().parents[1] / "scripts" / "configure_feishu_webhook.command").read_text(encoding="utf-8")

        self.assertIn("FEISHU_APP_ID", command)
        self.assertIn("FEISHU_APP_SECRET", command)
        self.assertNotIn("FEISHU_IMAGE_KEY=", command)


if __name__ == "__main__":
    unittest.main()
