#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${OPENCLAW_PYTHON:-$HOME/Documents/New project/.venv313/bin/python}"
exec "$PYTHON_BIN" "$PROJECT_DIR/scripts/production_health.py" "$@"
