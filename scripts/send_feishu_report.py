"""Send a Markdown/text report to a Feishu custom bot webhook.

Environment:
  FEISHU_WEBHOOK_URL     Required. Custom bot webhook URL.
  FEISHU_WEBHOOK_SECRET  Optional. Bot signing secret.
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import shlex
import time
import urllib.error
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = PROJECT_ROOT / ".secrets" / "feishu_webhook.env"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--title", default="OpenClaw 项目进展更新")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--msg-type", choices=("post", "text"), default="post")
    return parser.parse_args()


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        if key in os.environ:
            continue
        try:
            os.environ[key] = shlex.split(value, posix=True)[0]
        except (IndexError, ValueError):
            os.environ[key] = value.strip().strip("'\"")


def sanitize_text(text: str) -> str:
    replacements = [
        (r"https://open\.feishu\.cn/open-apis/bot/v2/hook/[A-Za-z0-9._~:/?#@!$&'()*+,;=%-]+", "[redacted-feishu-webhook]"),
        (r"https?://(?:127\.0\.0\.1|localhost|0\.0\.0\.0|192\.168\.\d+\.\d+|\d{1,3}(?:\.\d{1,3}){3})(?::\d+)?[^\s`)]*", "[redacted-local-url]"),
        (r"\b(FEISHU_WEBHOOK_URL|FEISHU_WEBHOOK_SECRET|OPENCLAW_API_KEY|DISCORD_BOT_TOKEN|TRADE_SESSION_TOKEN)\s*=\s*['\"]?[^'\"\s]+", r"\1=[redacted]"),
        (r"\b(api[_-]?key|secret|token|webhook)\b\s*[:=]\s*['\"]?[A-Za-z0-9._~:/?#@!$&'()*+,;=%-]{8,}", r"\1=[redacted]"),
        (r"\b(port|socket port)\s+`?\d{2,5}`?", r"\1 [redacted-port]"),
    ]
    sanitized = text
    for pattern, replacement in replacements:
        sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)
    return sanitized


def clean_display_text(text: str) -> str:
    cleaned_lines = []
    for raw_line in text.splitlines():
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if not line:
            cleaned_lines.append("")
            continue
        line = re.sub(r"^#{1,6}\s*", "", line)
        line = line.replace("`", "")
        line = re.sub(r"\*\*(.*?)\*\*", r"\1", line)
        if indent >= 2:
            line = "  " + line
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()


def report_to_post_content(text: str) -> list[list[dict[str, str]]]:
    rows: list[list[dict[str, str]]] = []
    for raw_line in clean_display_text(text).splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r"^[一二三四五六七八九十]+、", stripped):
            line = f"\n{stripped}"
        elif line.startswith("  - "):
            line = f"  ◦ {line[4:]}"
        elif stripped.startswith("- "):
            line = f"• {stripped[2:]}"
        rows.append([{"tag": "text", "text": line}])
    return rows or [[{"tag": "text", "text": "今日暂无可汇报更新。"}]]


def build_text_payload(title: str, text: str) -> dict[str, object]:
    return {
        "msg_type": "text",
        "content": {"text": f"{title}\n\n{clean_display_text(text)}"},
    }


def build_post_payload(title: str, text: str) -> dict[str, object]:
    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title,
                    "content": report_to_post_content(text),
                }
            }
        },
    }


def sign_payload(payload: dict[str, object], secret: str | None) -> dict[str, object]:
    if secret:
        timestamp = str(int(time.time()))
        string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
        sign = base64.b64encode(
            hmac.new(string_to_sign, b"", hashlib.sha256).digest()
        ).decode("utf-8")
        payload["timestamp"] = timestamp
        payload["sign"] = sign
    return payload


def main() -> int:
    args = parse_args()
    load_env_file(args.env_file)
    webhook_url = os.getenv("FEISHU_WEBHOOK_URL", "").strip()
    if not webhook_url:
        raise SystemExit("FEISHU_WEBHOOK_URL is required")
    text = sanitize_text(args.report.read_text(encoding="utf-8"))
    if args.msg_type == "text":
        payload = build_text_payload(args.title, text)
    else:
        payload = build_post_payload(args.title, text)
    payload = sign_payload(payload, os.getenv("FEISHU_WEBHOOK_SECRET"))
    request = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            print(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Feishu webhook failed: HTTP {exc.code}: {body}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
