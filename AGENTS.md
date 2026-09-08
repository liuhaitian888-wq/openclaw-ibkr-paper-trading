# Repository Instructions

## Secret Scanning

- Before committing, opening a PR, or reporting work as complete, run `pre-commit run gitleaks --all-files` when `pre-commit` is available.
- If `pre-commit` is unavailable but `gitleaks` is installed, run `gitleaks detect --source . --no-git --redact --verbose`.
- Never commit real secrets. Keep local credentials in ignored files such as `.env` or `.secrets/`, and use `.env.example` for placeholders.
- Treat any gitleaks finding as blocking until it is removed or explicitly documented as a false positive.

## Production engineering

- First read PRODUCTION.md and run the read-only health/smoke entry. Respect maintenance and PAUSED; do not start/send/trade to make a check green.
- Develop and run the complete offline suite only in a linked worktree, with `python scripts/run_worktree_tests.py`. It isolates state and disables real TCP connections. Never point tests at production DB/ledger.
- After worktree tests and secret scan pass, commit there and merge/cherry-pick through Git into the designated production workspace/branch. Preserve other uncommitted work. The production workspace runs only the quick smoke check; repeat full tests there only if the user explicitly overrides this workflow.
- Worktrees may not host long-running production services. Production code comes from the approved main workspace; persistent state uses `~/.local/state/openclaw`, never cwd or a worktree. Do not silently activate an unverified migration candidate.
- Every file/SQLite/HTTP/subprocess resource needs a lifecycle owner. SQLite transaction context managers do not close connections; use closing + a transaction scope. Long-lived clients have one owner, bounded shutdown, and no duplicate worker creation.
- Never hide a leak by raising fd limits or scanning and forcibly closing unrelated fds. Observe FD/RSS/CPU/thread/child trends; warn at 70% and critical at 85% of the process soft FD limit, or sustained growth. Diagnostics must not kill peers or send alerts externally.
- Startup must validate workspace, approved commit/branch/state manifest, maintenance gate, and a held kernel service lock; log deployment identity and paths. Reject duplicates instead of killing them.
- Recheck the dependency chain before retries. UNKNOWN or non-idempotent outcomes require reconciliation and must never be automatically replayed. Distinguish entity identity, event occurrence, and exact-content fingerprints; never add BUY/SELL blindly to a key.
- Keep source backups and provenance until reconciliation is complete. Do not delete uncommitted/unmerged worktrees or legacy state based on filename or age alone.

- Module dependency changes belong in the shared reporting.health registry/resolver. Persist stale/recovery/operation state locally; network restoration never implies business permission.
- Recovery callbacks must be bounded read-only/idempotent operations. UNKNOWN/STARTED side effects survive restart and never auto-replay. Do not install an unverified adapter merely to turn health green.
- Treat manual/external broker orders as normal exposure. Absence of a local strategy intent is not sufficient to claim ownership or cancel an order. Verify account/environment and retain broker exposure for risk checks.
