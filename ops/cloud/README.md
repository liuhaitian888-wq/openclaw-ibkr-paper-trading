# Paper cloud deployment

Production code: `/opt/openclaw/app` (a real Git checkout, never a worktree).
Runtime: `/opt/openclaw/venv`; state: `/home/ibkr/.local/state/openclaw`.
Use the official Gateway installer and official API SDK; record installer hashes
and `pip freeze` in deployment evidence. Never install credentials into Git.

`install-host.sh` installs the supervised GUI and Gateway units. It deliberately
does not install or activate a strategy unit. Keep PAUSED and runtime/MAINTENANCE
until historical reconciliation, exact Paper identity, and the production
manifest have been independently verified. No candidate database is production.

Desktop access is SSH authenticated: forward local 16080 to remote 127.0.0.1:6080.
X11 has a private authorization cookie; VNC and noVNC bind only to loopback.
VNC additionally requires a random desktop password, provisioned outside Git;
store its VNC verifier at mode-0600 `/home/ibkr/.vnc/passwd` before installation.
All remote desktop access requires the dedicated SSH key. Never open
5900/6080/4002/8789. Do not pass the desktop password in a browser URL.
Only the human enters IBKR credentials, chooses Paper Trading, completes 2FA,
sets Paper port 4002, enables read-only API, and accepts localhost API access.
Do not store or automate an IBKR password or bypass weekly reauthentication.
Use Gateway's supported auto-restart setting after inspecting its GUI.
Gateway process recovery can return to login; process uptime is not API readiness.

`paper_readback.py` is bounded and read-only. It requires an exact approved Paper
account and streaming L1 requests (no paid snapshots). Save its output in private
state, not Git. A complete snapshot does not prove historical fills are complete.
Compare executions, permanent order IDs, account, orderRef, positions and pending
intent provenance against preserved source history and Paper Flex statements.
An UNKNOWN outcome stays blocked and must never be resubmitted automatically.

Only desktop/Gateway and bounded read-only monitoring may start before reconciliation. Gateway uses systemd restart
after both clean exits and failures, a private display, logs in the journal,
and a fixed memory budget. An explicit `systemctl stop` still leaves it stopped.
No mail sender credentials are included. SMTP and an external host-loss monitor
must be provisioned and delivery verified before unattended acceptance.

`host_status.py` runs the existing read-only smoke and writes private local
evidence every five minutes. `alert_email.py` is a separate, initially disarmed
worker. It needs mode-0600 `~/.config/openclaw/smtp.json` with a dedicated SMTP
relay's host, port (STARTTLS), sender, username and relay_password, plus the
explicit `runtime/EMAIL_ALERTS_ARMED` file. Never use the main Hotmail or IBKR
password. Test delivery before enabling ibkr-email.timer. This local worker
cannot detect total host loss; configure an independent external monitor too.

`backup_state.py` snapshots each published SQLite database with the online backup
API, checks readability, compresses it and records a hash. These snapshots are
individually consistent, not atomic across databases. Restore only into an
isolated directory, with execution paused and fresh broker reconciliation.
Backups stay on disk until an explicit retention/export policy is approved;
watch disk usage. Host-local backups do not survive host deletion. Quarantined
migration evidence is preserved separately and is never restored automatically.

External monitoring alternative: Healthchecks.io's free plan can send the email
itself, so a local SMTP relay is optional. Human registration and mailbox
verification precede use. Configure two checks (host and Paper API), period five
minutes and grace five minutes, using generic names and the recipient's email.
Store `host_url` and `paper_api_url` in mode-0600
`~/.config/openclaw/healthchecks.json`; these URLs are credentials. No logs or
financial data are sent. Verify both a failure email and a recovery email.

After an exact successful human-authenticated Paper readback, provision private
`paper-observer.json` with `expected_account` and up to five `symbols`. Enable
ibkr-readback.timer for bounded snapshots in private `observations/`, separate
from production readiness. Enable ibkr-heartbeat.timer only after its checks are
configured. Host and API heartbeats do not imply trading authorization or fresh
market data; the existing module resolver and order gates remain authoritative.
Frozen/closed-market prices must not be mistaken for authentication failure.

Acceptance requires at least 192 real hours, a weekly authentication boundary,
process and network failure recovery, full host reboot, consistent SQLite backup
restore, confirmed email delivery, and broker/local order-position comparison.
Do not claim a seven-day test passed from offline tests or host uptime alone.
