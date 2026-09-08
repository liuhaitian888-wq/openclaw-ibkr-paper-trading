#!/bin/zsh
set -euo pipefail
cd "$(dirname "$0")/.."
exec scripts/send_daily_feishu_update_if_due.command
