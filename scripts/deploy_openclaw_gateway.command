#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ARCHIVE_NAME="openclaw_trading_gateway.tar.gz"
DESKTOP_ARCHIVE="$HOME/Desktop/$ARCHIVE_NAME"
SHARED_DIR="/Volumes/openclaw_shared"
VM_HOST="${OPENCLAW_VM_HOST:-192.168.64.2}"
VM_USER="${OPENCLAW_VM_USER:-nbhsbgnb}"
VM_KEY="${OPENCLAW_VM_KEY:-$HOME/.ssh/openclaw_vm_ed25519}"
API_URL="${TRADING_API_URL:-http://192.168.64.1:8787}"

cd "$PROJECT_DIR"

if [[ -f ".secrets/openclaw_api_key" ]]; then
  HEALTH="$(
    curl -fsS -H "X-API-Key: $(cat .secrets/openclaw_api_key)" "$API_URL/health" 2>/dev/null || true
  )"
  if [[ -n "$HEALTH" ]]; then
    KILL_SWITCH="$(
      printf '%s' "$HEALTH" | .venv313/bin/python -c 'import json,sys; print(json.load(sys.stdin).get("kill_switch_enabled"))'
    )"
    if [[ "$KILL_SWITCH" != "True" ]]; then
      echo "Refusing deployment: Mac API is not in DEV_LOCK/STOP."
      echo "Current health: $HEALTH"
      echo "Switch to DEV_LOCK or STOP before deploying code."
      exit 1
    fi
  else
    echo "Mac API health not reachable; treating this as STOP for deployment."
  fi
else
  echo "Missing .secrets/openclaw_api_key; cannot check Mac API health."
  exit 1
fi

COPYFILE_DISABLE=1 tar \
  --exclude='openclaw/.secrets' \
  --exclude='openclaw/__pycache__' \
  --exclude='openclaw/.*.pyc' \
  -czf "$DESKTOP_ARCHIVE" openclaw

echo "Packaged: $DESKTOP_ARCHIVE"

if [[ -d "$SHARED_DIR" ]]; then
  cp "$DESKTOP_ARCHIVE" "$SHARED_DIR/$ARCHIVE_NAME"
  echo "Copied to shared folder: $SHARED_DIR/$ARCHIVE_NAME"
else
  echo "Shared folder not mounted at $SHARED_DIR."
  echo "Will use SSH/scp fallback if the VM is reachable."
fi

SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=5)
if [[ -f "$VM_KEY" ]]; then
  SSH_OPTS+=(-i "$VM_KEY")
fi

if ssh "${SSH_OPTS[@]}" "$VM_USER@$VM_HOST" 'true' >/dev/null 2>&1; then
  echo "SSH reachable: $VM_USER@$VM_HOST"
  REMOTE_ARCHIVE="/mnt/openclaw_shared/$ARCHIVE_NAME"
  if [[ ! -d "$SHARED_DIR" ]]; then
    REMOTE_ARCHIVE="/tmp/$ARCHIVE_NAME"
    scp "${SSH_OPTS[@]}" "$DESKTOP_ARCHIVE" "$VM_USER@$VM_HOST:$REMOTE_ARCHIVE"
    echo "Copied through SSH: $VM_USER@$VM_HOST:$REMOTE_ARCHIVE"
  fi
  ssh "${SSH_OPTS[@]}" "$VM_USER@$VM_HOST" "REMOTE_ARCHIVE='$REMOTE_ARCHIVE' bash -s" <<'REMOTE'
set -euo pipefail
mkdir -p ~/.openclaw/ibkr-paper-gateway
tar -xzf "$REMOTE_ARCHIVE" \
  -C ~/.openclaw/ibkr-paper-gateway \
  --strip-components=1
python3 -m py_compile ~/.openclaw/ibkr-paper-gateway/openclaw_trading_client.py
echo "Linux OpenClaw gateway client updated."
echo "Long-term key preserved at ~/.openclaw/ibkr-paper-gateway/.secrets/openclaw_api_key"
REMOTE
else
  echo "SSH not reachable for $VM_USER@$VM_HOST."
  echo "Set OPENCLAW_VM_HOST/OPENCLAW_VM_USER/OPENCLAW_VM_KEY or configure SSH."
fi

cat <<'INSTRUCTIONS'

Linux VM update command:

  mkdir -p ~/.openclaw/ibkr-paper-gateway
  tar -xzf /mnt/openclaw_shared/openclaw_trading_gateway.tar.gz \
    -C ~/.openclaw/ibkr-paper-gateway \
    --strip-components=1

This update does not delete ~/.openclaw/ibkr-paper-gateway/.secrets.
INSTRUCTIONS
