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
VNC has no separate password: server-local users must be trusted, and all remote
desktop access requires the dedicated SSH key. Never open 5900/6080/4002/8789.
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

Only desktop/Gateway may start before reconciliation. Gateway uses systemd restart
on failure, a private display, logs in the journal, and a fixed memory budget.
No mail sender credentials are included. SMTP and an external host-loss monitor
must be provisioned and delivery verified before unattended acceptance.

Acceptance requires at least 192 real hours, a weekly authentication boundary,
process and network failure recovery, full host reboot, consistent SQLite backup
restore, confirmed email delivery, and broker/local order-position comparison.
Do not claim a seven-day test passed from offline tests or host uptime alone.
