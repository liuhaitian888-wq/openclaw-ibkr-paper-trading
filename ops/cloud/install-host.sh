#!/usr/bin/env bash
set -euo pipefail
[[ $(id -u) == 0 ]] || { echo 'Run as root'; exit 1; }
base=$(cd -- "$(dirname -- "$0")" && pwd)
id ibkr >/dev/null
test -x /home/ibkr/Jts/ibgateway
test -f /home/ibkr/.vnc/passwd
install -d -o ibkr -g ibkr -m 700 /home/ibkr/.local/state/openclaw/{runtime,logs,backups}
touch /home/ibkr/.local/state/openclaw/PAUSED /home/ibkr/.local/state/openclaw/runtime/MAINTENANCE
chown ibkr:ibkr /home/ibkr/.local/state/openclaw/PAUSED /home/ibkr/.local/state/openclaw/runtime/MAINTENANCE
install -o root -g root -m 755 "$base/start-display.sh" /usr/local/bin/ibkr-start-display
install -o root -g root -m 644 "$base"/systemd/*.service /etc/systemd/system/
install -o root -g root -m 644 "$base"/systemd/*.timer /etc/systemd/system/
install -d -m 755 /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/ibkr-storage.conf <<'EOF'
[Journal]
Storage=persistent
SystemMaxUse=256M
MaxRetentionSec=14day
EOF
systemctl daemon-reload
systemctl restart systemd-journald
systemd-analyze verify "$base"/systemd/*.service "$base"/systemd/*.timer
# Enable infrastructure only; no strategy or account operation is authorized here.
systemctl enable --now ibkr-display.service ibkr-desktop.service ibkr-vnc.service ibkr-web-vnc.service ibkr-gateway.service
