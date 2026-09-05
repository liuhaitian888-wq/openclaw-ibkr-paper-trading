"""Generate and send the daily Paper Trading visual report to Feishu deehub.

This is the official scheduled delivery path. It keeps Markdown/QA artifacts
local for diagnostics, but sends only the PNG image to Feishu when successful.
If image delivery fails, it sends a short failure notification instead of the
old long QA text report.
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
    build_image_payload,
    build_text_payload,
    feishu_image_capability,
    load_env_file,
    require_target,
    sanitize_text,
    send_webhook_payload,
    upload_image,
)


DEFAULT_ENV_FILE = PROJECT_ROOT / ".secrets" / "feishu_webhook.env"
FAILURE_MESSAGE = "买 der 日报图片发送失败，请检查 Feishu image upload。"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
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


def send_failure_notification(title: str, detail: str) -> str | None:
    text = f"{FAILURE_MESSAGE}\n原因：{sanitize_text(detail)}"
    try:
        return send_webhook_payload(build_text_payload(title, text))
    except Exception as exc:  # noqa: BLE001 - failure path must not leak or mask original image failure
        print(f"Feishu short failure notification failed: {sanitize_text(str(exc))}", file=sys.stderr)
        return None


def send_daily_visual_update(
    *,
    env_file: Path = DEFAULT_ENV_FILE,
    require_target_name: str = "deehub",
    title: str = "买 der · Visual Paper Trading 日报",
    failure_title: str = "买 der · Paper Trading 日报发送失败",
    report_path: Path = REPORT_DIR / "latest.json",
    output_dir: Path = REPORT_DIR,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> dict[str, Any]:
    load_env_file(env_file)
    require_target(require_target_name)
    qa_path = write_local_qa_markdown(output_dir)
    manifest = write_visual_report(report_path, output_dir=output_dir, width=width, height=height)
    image_path = Path(str(manifest["image_path"]))
    try:
        capability = feishu_image_capability()
        if not capability["ready"]:
            raise RuntimeError(str(capability["blocked_reason"]))
        image_key = upload_image(image_path)
        response = send_webhook_payload(build_image_payload(image_key))
        return {
            "status": "sent",
            "response": response,
            "image_path": str(image_path),
            "html_path": manifest["html_path"],
            "manifest_path": str(output_dir / "visual_report_manifest.json"),
            "qa_markdown_path": str(qa_path),
            "image_size": manifest["image_size"],
            "image_width": manifest["image_width"],
            "image_height": manifest["image_height"],
        }
    except Exception as exc:  # noqa: BLE001 - convert image failure into one short Feishu notification
        detail = sanitize_text(str(exc))
        notification_response = send_failure_notification(failure_title, detail)
        return {
            "status": "image_failed",
            "error": detail,
            "failure_notification_sent": notification_response is not None,
            "failure_notification_response": notification_response,
            "image_path": str(image_path),
            "html_path": manifest["html_path"],
            "manifest_path": str(output_dir / "visual_report_manifest.json"),
            "qa_markdown_path": str(qa_path),
        }


def main() -> int:
    args = parse_args()
    result = send_daily_visual_update(
        env_file=args.env_file,
        require_target_name=args.require_target,
        title=args.title,
        failure_title=args.failure_title,
        report_path=args.report,
        output_dir=args.output_dir,
        width=args.width,
        height=args.height,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") == "sent" else 1


if __name__ == "__main__":
    raise SystemExit(main())
