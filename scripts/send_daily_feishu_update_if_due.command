#!/bin/zsh
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON_BIN="${PYTHON_BIN:-/Users/nbhsbgnb/Documents/New project/.venv313/bin/python}"
exec "$PYTHON_BIN" scripts/report_production_scheduler.py
