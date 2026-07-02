#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -f ".env" ]]; then
  set -a
  source ".env"
  set +a
fi

if [[ -z "${DISCORD_BOT_TOKEN:-}" ]]; then
  echo "DISCORD_BOT_TOKEN is required" >&2
  exit 1
fi

if [[ -z "${DISCORD_CHANNEL_IDS:-}" ]]; then
  echo "DISCORD_CHANNEL_IDS is required" >&2
  exit 1
fi

.venv313/bin/python -m discord_handbook.bot
