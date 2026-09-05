#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p .secrets

read -r "webhook_url?Paste FEISHU_WEBHOOK_URL: "
read -rs "webhook_secret?Paste FEISHU_WEBHOOK_SECRET: "
printf '\n'
read -r "app_id?Paste FEISHU_APP_ID for image upload (optional): "
read -rs "app_secret?Paste FEISHU_APP_SECRET for image upload (optional): "
printf '\n'
read -r "target_name?Paste FEISHU_TARGET_NAME (for example: deehub): "

if [[ -z "$webhook_url" ]]; then
  echo "FEISHU_WEBHOOK_URL is required." >&2
  exit 1
fi

{
  printf 'FEISHU_WEBHOOK_URL=%q\n' "$webhook_url"
  if [[ -n "$webhook_secret" ]]; then
    printf 'FEISHU_WEBHOOK_SECRET=%q\n' "$webhook_secret"
  fi
  if [[ -n "$app_id" ]]; then
    printf 'FEISHU_APP_ID=%q\n' "$app_id"
  fi
  if [[ -n "$app_secret" ]]; then
    printf 'FEISHU_APP_SECRET=%q\n' "$app_secret"
  fi
  if [[ -n "$target_name" ]]; then
    printf 'FEISHU_TARGET_NAME=%q\n' "$target_name"
  fi
} > .secrets/feishu_webhook.env

chmod 600 .secrets/feishu_webhook.env
echo "Saved Feishu webhook config to .secrets/feishu_webhook.env"
