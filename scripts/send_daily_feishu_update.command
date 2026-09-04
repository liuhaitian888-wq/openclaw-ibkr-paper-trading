#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")/.."
PYTHON_BIN="${PYTHON_BIN:-/Users/nbhsbgnb/Documents/New project/.venv313/bin/python}"
FEISHU_WEBHOOK_ENV_FILE="${FEISHU_WEBHOOK_ENV_FILE:-/Users/nbhsbgnb/Documents/New project/.secrets/feishu_webhook.env}"

REPORT_PATH="$(
  "$PYTHON_BIN" scripts/generate_daily_feishu_update.py
)"

"$PYTHON_BIN" scripts/send_feishu_report.py "$REPORT_PATH" \
  --title "买 der · Paper Trading 日报" \
  --env-file "$FEISHU_WEBHOOK_ENV_FILE" \
  --require-target "deehub"
