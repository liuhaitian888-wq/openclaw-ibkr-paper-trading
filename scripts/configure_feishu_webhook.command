#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p .secrets

read -r "webhook_url?Paste FEISHU_WEBHOOK_URL: "
read -rs "webhook_secret?Paste FEISHU_WEBHOOK_SECRET: "
printf '\n'

if [[ -z "$webhook_url" ]]; then
  echo "FEISHU_WEBHOOK_URL is required." >&2
  exit 1
fi

{
  printf 'FEISHU_WEBHOOK_URL=%q\n' "$webhook_url"
  if [[ -n "$webhook_secret" ]]; then
    printf 'FEISHU_WEBHOOK_SECRET=%q\n' "$webhook_secret"
  fi
} > .secrets/feishu_webhook.env

chmod 600 .secrets/feishu_webhook.env
echo "Saved Feishu webhook config to .secrets/feishu_webhook.env"
