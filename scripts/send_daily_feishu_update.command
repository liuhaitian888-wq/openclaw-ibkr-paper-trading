#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")/.."

REPORT_PATH="$(
  .venv313/bin/python scripts/generate_daily_feishu_update.py
)"

.venv313/bin/python scripts/send_feishu_report.py "$REPORT_PATH" \
  --title "OpenClaw 每日项目进展更新"
