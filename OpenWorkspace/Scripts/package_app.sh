#!/usr/bin/env bash
set -euo pipefail

CONFIGURATION="${1:-release}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT_DIR/.build/OpenWorkspace.app"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"

swift build -c "$CONFIGURATION" --package-path "$ROOT_DIR"

rm -rf "$APP_DIR"
mkdir -p "$MACOS_DIR"
cp "$ROOT_DIR/Packaging/OpenWorkspace.app/Contents/Info.plist" "$CONTENTS_DIR/Info.plist"
cp "$ROOT_DIR/.build/$CONFIGURATION/OpenWorkspace" "$MACOS_DIR/OpenWorkspace"
chmod +x "$MACOS_DIR/OpenWorkspace"

echo "$APP_DIR"
