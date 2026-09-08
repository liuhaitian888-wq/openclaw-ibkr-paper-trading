#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENTRY="$PROJECT_DIR/scripts/ibkr_paper_app_entry.py"

usage() {
  cat <<'EOF'
IBKR Paper Platform

  ./scripts/paper_platform.command install   Auto-open TWS at macOS login
  ./scripts/paper_platform.command start     Open TWS Paper login window now
  ./scripts/paper_platform.command status    Show TWS/Paper-port status
  ./scripts/paper_platform.command safe-api  Start Python API in DEV_LOCK
  ./scripts/paper_platform.command uninstall Remove TWS auto-open service

This command never enters IBKR credentials and never starts an order Agent.
Use TWS Paper Trading login and complete IBKR authentication manually.
EOF
}

action="${1:-status}"
case "$action" in
  install)
    exec /usr/bin/python3 "$ENTRY" install
    ;;
  start)
    exec /usr/bin/python3 "$ENTRY" open
    ;;
  status)
    exec /usr/bin/python3 "$ENTRY" status
    ;;
  safe-api)
    echo "Starting the Python API in DEV_LOCK: kill switch on, transmission off."
    exec "$PROJECT_DIR/scripts/start_dev_lock_api.command"
    ;;
  uninstall)
    exec /usr/bin/python3 "$ENTRY" uninstall
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
