#!/usr/bin/env bash
set -euo pipefail
umask 077
test -n "${XAUTHORITY:-}"
touch "$XAUTHORITY"
xauth -f "$XAUTHORITY" add :99 . "$(openssl rand -hex 16)"
exec /usr/bin/Xvfb :99 -screen 0 1280x900x24 -nolisten tcp -noreset -auth "$XAUTHORITY"
