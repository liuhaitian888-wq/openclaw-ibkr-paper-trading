"""Send a Markdown/text/image report to a Feishu custom bot webhook.

Environment:
  FEISHU_WEBHOOK_URL     Required. Custom bot webhook URL.
  FEISHU_WEBHOOK_SECRET  Optional. Bot signing secret.
  FEISHU_APP_ID          Optional. Required for local image upload.
  FEISHU_APP_SECRET      Optional. Required for local image upload.
"""

import sys as _sys
from pathlib import Path as _Path
if __package__ in (None, ""):
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
from trading.production_paths import PAUSED

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
import uuid
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = PROJECT_ROOT / ".secrets" / "feishu_webhook.env"
PAUSE_MARKER = PAUSED


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--title", default="OpenClaw 项目进展更新")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--msg-type", choices=("post", "text", "image"), default="post")
    parser.add_argument("--require-target", default="", help="Require FEISHU_TARGET_NAME/FEISHU_WEBHOOK_NAME to match before sending.")
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


def feishu_image_capability() -> dict[str, object]:
    has_webhook = bool(os.getenv("FEISHU_WEBHOOK_URL", "").strip())
    has_image_key = bool(os.getenv("FEISHU_IMAGE_KEY", "").strip())
    has_upload_credentials = bool(
        os.getenv("FEISHU_TENANT_ACCESS_TOKEN", "").strip()
        or (os.getenv("FEISHU_APP_ID", "").strip() and os.getenv("FEISHU_APP_SECRET", "").strip())
    )
    return {
        "webhook_image_message": has_webhook,
        "direct_image_key": has_image_key,
        "image_upload": has_upload_credentials,
        "ready": has_webhook and (has_image_key or has_upload_credentials),
        "blocked_reason": "" if has_webhook and (has_image_key or has_upload_credentials) else "missing Feishu image upload credentials or FEISHU_IMAGE_KEY",
    }


def build_image_payload(image_key: str) -> dict[str, object]:
    return {"msg_type": "image", "content": {"image_key": image_key}}


def tenant_access_token(*, force_refresh: bool = False) -> str:
    existing = os.getenv("FEISHU_TENANT_ACCESS_TOKEN", "").strip()
    if existing and not force_refresh:
        return existing
    app_id = os.getenv("FEISHU_APP_ID", "").strip()
    app_secret = os.getenv("FEISHU_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        raise RuntimeError("missing Feishu image upload credentials")
    request = urllib.request.Request(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        data=json.dumps({"app_id": app_id, "app_secret": app_secret}).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    validate_feishu_response(json.dumps(payload), context="Feishu token")
    token = str(payload.get("tenant_access_token") or "")
    if not token:
        raise RuntimeError("Feishu token response missing tenant_access_token")
    return token


def upload_image(path: Path) -> str:
    token = tenant_access_token()
    boundary = "----codex-feishu-" + uuid.uuid4().hex
    image_bytes = path.read_bytes()
    filename = path.name.encode("utf-8")
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="image_type"\r\n\r\n',
            b"message\r\n",
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="image"; filename="' + filename + b'"\r\n',
            b"Content-Type: image/png\r\n\r\n",
            image_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    request = urllib.request.Request(
        "https://open.feishu.cn/open-apis/im/v1/images",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    validate_feishu_response(json.dumps(payload), context="Feishu upload")
    image_key = str((payload.get("data") or {}).get("image_key") or "")
    if not image_key.startswith("img_"):
        raise RuntimeError("Feishu image upload response missing image_key")
    return image_key


def sign_payload(payload: dict[str, object], secret: str | None) -> dict[str, object]:
    payload = dict(payload)
    if secret:
        timestamp = str(int(time.time()))
        string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
        sign = base64.b64encode(
            hmac.new(string_to_sign, b"", hashlib.sha256).digest()
        ).decode("utf-8")
        payload["timestamp"] = timestamp
        payload["sign"] = sign
    return payload


class FeishuBusinessRejected(RuntimeError):
    """An explicit nonzero Feishu business acknowledgement."""


def send_webhook_payload(payload: dict[str, object], *, timeout: int = 15) -> str:
    if (PAUSED).exists():
        raise RuntimeError("Report delivery is paused by incident control")
    from scripts.report_delivery_guard import DELIVERY_AUTHORIZED
    if not DELIVERY_AUTHORIZED.get():
        raise RuntimeError("Direct report transport disabled; use guarded sender")
    webhook_url = os.getenv("FEISHU_WEBHOOK_URL", "").strip()
    if not webhook_url:
        raise RuntimeError("FEISHU_WEBHOOK_URL is required")
    signed_payload = sign_payload(payload, os.getenv("FEISHU_WEBHOOK_SECRET"))
    request = urllib.request.Request(
        webhook_url,
        data=json.dumps(signed_payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_text = response.read().decode("utf-8")
            validate_feishu_response(response_text, context="Feishu webhook")
            return response_text
    except urllib.error.HTTPError as exc:
        body = sanitize_text(exc.read().decode("utf-8", errors="replace"))
        raise RuntimeError(f"Feishu webhook failed: HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Feishu webhook failed: {sanitize_text(str(exc))}") from exc


def validate_feishu_response(response_text: str, *, context: str) -> None:
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Unrecognized Feishu acknowledgement") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Unrecognized Feishu acknowledgement")
    codes = [payload[key] for key in ("code", "StatusCode") if key in payload]
    if codes and all(type(code) is int and code == 0 for code in codes):
        return
    if not codes or any(type(code) is not int for code in codes):
        raise RuntimeError("Unrecognized Feishu acknowledgement")
    code = codes[0] if len(codes) == 1 else codes
    error = FeishuBusinessRejected(f"{context} failed: code={code} msg={sanitize_text(str(payload.get('msg') or ''))}")
    error.business_code = code
    raise error


def configured_target_name() -> str:
    return (
        os.getenv("FEISHU_TARGET_NAME", "")
        or os.getenv("FEISHU_WEBHOOK_NAME", "")
        or os.getenv("FEISHU_CHAT_NAME", "")
    ).strip()


def require_target(expected: str) -> None:
    if not expected:
        return
    actual = configured_target_name()
    if actual.lower() != expected.strip().lower():
        seen = actual or "missing"
        raise SystemExit(f"Feishu target mismatch: expected {expected}, configured {seen}")


from trading.production_guard import guarded_service

@guarded_service("sender")
def main() -> int:
    args = parse_args()
    if PAUSE_MARKER.exists():
        raise SystemExit(f"Report delivery is paused by incident control: {PAUSE_MARKER}")
    load_env_file(args.env_file)
    require_target(args.require_target)
    if args.msg_type == "image":
        capability = feishu_image_capability()
        if not capability["ready"]:
            raise SystemExit(f"Feishu image capability unavailable: {capability['blocked_reason']}")
        try:
            payload = build_image_payload(upload_image(args.report))
        except (OSError, RuntimeError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            raise SystemExit(f"Feishu image send failed: {sanitize_text(str(exc))}") from exc
    elif args.msg_type == "text":
        text = sanitize_text(args.report.read_text(encoding="utf-8"))
        payload = build_text_payload(args.title, text)
    else:
        text = sanitize_text(args.report.read_text(encoding="utf-8"))
        payload = build_post_payload(args.title, text)
    try:
        print(send_webhook_payload(payload))
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
