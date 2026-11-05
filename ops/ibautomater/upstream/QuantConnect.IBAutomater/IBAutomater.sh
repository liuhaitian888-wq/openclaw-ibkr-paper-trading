#!/bin/bash
set -euo pipefail
: "${DISPLAY:?Existing private display is required}"
: "${XAUTHORITY:?Existing private Xauthority is required}"
export JAVA_TOOL_OPTIONS="$2"
executable="$1"
shift 2
exec "$executable" "$@"
