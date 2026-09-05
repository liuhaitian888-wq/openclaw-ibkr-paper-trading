#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")/.."
PYTHON_BIN="${PYTHON_BIN:-/Users/nbhsbgnb/Documents/New project/.venv313/bin/python}"
FEISHU_WEBHOOK_ENV_FILE="${FEISHU_WEBHOOK_ENV_FILE:-/Users/nbhsbgnb/Documents/New project/.secrets/feishu_webhook.env}"

REPORT_PATH="$(
  "$PYTHON_BIN" scripts/generate_daily_feishu_update.py
)"

if VISUAL_MANIFEST="$("$PYTHON_BIN" scripts/daily_visual_report.py 2>&1)"; then
  VISUAL_PNG="$("$PYTHON_BIN" - <<'PY'
import json
try:
    print(json.load(open("reports/daily_trading/visual_report_manifest.json", encoding="utf-8")).get("image_path", ""))
except Exception:
    print("")
PY
)"
  if [[ -n "$VISUAL_PNG" ]]; then
    "$PYTHON_BIN" scripts/send_feishu_report.py "$VISUAL_PNG" \
      --title "买 der · Paper Trading 图片日报" \
      --env-file "$FEISHU_WEBHOOK_ENV_FILE" \
      --require-target "deehub" \
      --msg-type image || true
  fi
else
  printf 'visual report generation failed; continuing with text report: %s\n' "$VISUAL_MANIFEST" >&2
fi

"$PYTHON_BIN" scripts/send_feishu_report.py "$REPORT_PATH" \
  --title "买 der · Paper Trading 日报" \
  --env-file "$FEISHU_WEBHOOK_ENV_FILE" \
  --require-target "deehub"
