"""Generate and send the daily Paper Trading visual report to Feishu deehub.

This is the official scheduled delivery path. It keeps Markdown/QA artifacts
local for diagnostics, but sends only the PNG image to Feishu when successful.
Delivery failures are local only; durable gating prevents repeat notifications.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.daily_visual_report import DEFAULT_HEIGHT, DEFAULT_WIDTH, REPORT_DIR, write_visual_report
from scripts.generate_daily_feishu_update import build_feishu_report
from scripts.send_feishu_report import (
    FeishuBusinessRejected,
    build_image_payload,
    feishu_image_capability,
    load_env_file,
    require_target,
    sanitize_text,
    send_webhook_payload,
    upload_image,
)


DEFAULT_ENV_FILE = Path("/Users/nbhsbgnb/Documents/New project/.secrets/feishu_webhook.env")
DEFAULT_UPLOAD_ENV_FILE = DEFAULT_ENV_FILE.with_name("feishu_image_upload.env")
FAILURE_MESSAGE = "买 der 日报图片发送失败，请检查 Feishu image upload。"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--upload-env-file", type=Path, default=DEFAULT_UPLOAD_ENV_FILE)
    parser.add_argument("--require-target", default="deehub")
    parser.add_argument("--title", default="买 der · Visual Paper Trading 日报")
    parser.add_argument("--report", type=Path, default=REPORT_DIR / "latest.json")
    parser.add_argument("--output-dir", type=Path, default=REPORT_DIR)
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--failure-title", default="买 der · Paper Trading 日报发送失败")
    return parser.parse_args()


def write_local_qa_markdown(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "latest.md"
    path.write_text(build_feishu_report(), encoding="utf-8")
    return path


def _send_daily_visual_update(
    *,
    env_file: Path = DEFAULT_ENV_FILE,
    upload_env_file: Path = DEFAULT_UPLOAD_ENV_FILE,
    require_target_name: str = "deehub",
    title: str = "买 der · Visual Paper Trading 日报",
    failure_title: str = "买 der · Paper Trading 日报发送失败",
    report_path: Path = REPORT_DIR / "latest.json",
    output_dir: Path = REPORT_DIR,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> dict[str, Any]:
    load_env_file(env_file)
    load_env_file(upload_env_file)
    require_target(require_target_name)
    qa_path = write_local_qa_markdown(output_dir)
    manifest = write_visual_report(report_path, output_dir=output_dir, width=width, height=height)
    image_path = Path(str(manifest["image_path"]))
    stage = "preflight"
    upload_result = {"status": "NOT_STARTED"}
    webhook_result = {"status": "NOT_STARTED"}
    try:
        capability = feishu_image_capability()
        if not capability["ready"]:
            raise RuntimeError(str(capability["blocked_reason"]))
        stage = "image_upload"
        upload_result = {"status": "REQUESTING"}
        image_key = upload_image(image_path)
        if not isinstance(image_key, str) or not image_key.startswith("img_"):
            raise RuntimeError("Upload response lacks valid image_key")
        upload_result = {"status": "SUCCESS", "business_code": 0, "valid_image_key": True}
        stage = "message_send"
        webhook_result = {"status": "REQUESTING"}
        response = send_webhook_payload(build_image_payload(image_key))
        from scripts.report_acknowledgement import classify
        acknowledgement = classify(response, 'custom_webhook')
        webhook_result = {"status": "BUSINESS_SUCCESS", "business_code": 0, "message_id": acknowledgement['message_id']}
        return {
            **acknowledgement,
            "image_upload_result": upload_result,
            "webhook_result": webhook_result,
            "error_code": None,
            "upload_confirmed": True,
            "image_key_valid": True,
            "response": response,
            "image_path": str(image_path),
            "html_path": manifest["html_path"],
            "manifest_path": str(output_dir / "visual_report_manifest.json"),
            "qa_markdown_path": str(qa_path),
            "image_size": manifest["image_size"],
            "image_width": manifest["image_width"],
            "image_height": manifest["image_height"],
        }
    except Exception as exc:  # noqa: BLE001 - keep diagnostics local; never retry ambiguity
        detail = sanitize_text(str(exc))
        outcome = 'FAILED' if isinstance(exc, FeishuBusinessRejected) else 'UNKNOWN'
        if stage == 'image_upload':
            upload_result = {'status': outcome, 'business_code': getattr(exc, 'business_code', None)}
        elif stage == 'message_send':
            webhook_result = {'status': outcome, 'business_code': getattr(exc, 'business_code', None)}
        notification_response = None  # Never turn a failed image into a repeating outbound alert.
        return {
            "status": ("BLOCKED" if stage == "preflight" else
                       "FAILED" if isinstance(exc, FeishuBusinessRejected) else "UNKNOWN"),
            "image_upload_result": upload_result,
            "webhook_result": webhook_result,
            "error_code": getattr(exc, "business_code", None),
            "stage": stage,
            "error": detail,
            "failure_notification_sent": notification_response is not None,
            "failure_notification_response": notification_response,
            "image_path": str(image_path),
            "html_path": manifest["html_path"],
            "manifest_path": str(output_dir / "visual_report_manifest.json"),
            "qa_markdown_path": str(qa_path),
        }


def send_daily_visual_update(**kwargs) -> dict[str, Any]:
    from scripts.report_delivery_guard import deliver
    report_path = kwargs.get("report_path", REPORT_DIR / "latest.json")
    return deliver(report_path, lambda: _send_daily_visual_update(**kwargs))


from trading.production_guard import guarded_service

@guarded_service("sender")
def main() -> int:
    args = parse_args()
    result = send_daily_visual_update(
        env_file=args.env_file,
        upload_env_file=args.upload_env_file,
        require_target_name=args.require_target,
        title=args.title,
        failure_title=args.failure_title,
        report_path=args.report,
        output_dir=args.output_dir,
        width=args.width,
        height=args.height,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") in ("SENT_ACCEPTED", "SENT_CONFIRMED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
