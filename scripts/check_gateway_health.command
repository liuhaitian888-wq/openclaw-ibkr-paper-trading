#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

API_KEY="$(cat .secrets/openclaw_api_key)"

curl -s \
  -H "X-API-Key: $API_KEY" \
  "http://192.168.64.1:8787/health" \
  | .venv313/bin/python -m json.tool
