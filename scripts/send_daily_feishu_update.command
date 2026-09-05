#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")/.."
PYTHON_BIN="${PYTHON_BIN:-/Users/nbhsbgnb/Documents/New project/.venv313/bin/python}"
FEISHU_WEBHOOK_ENV_FILE="${FEISHU_WEBHOOK_ENV_FILE:-/Users/nbhsbgnb/Documents/New project/.secrets/feishu_webhook.env}"

"$PYTHON_BIN" scripts/send_daily_visual_feishu_update.py \
  --env-file "$FEISHU_WEBHOOK_ENV_FILE" \
  --require-target "deehub" \
  --title "买 der · Visual Paper Trading 日报"
