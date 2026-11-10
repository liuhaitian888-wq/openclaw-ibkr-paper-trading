# Checked backup copies — 2026-11-10

## Scope and actual evidence

The report engineering continuation copied an existing Hetzner backup read-only into the existing Mac private engineering directory. It did not run another backup owner, restore live state, copy OAuth/cache/SSH credentials, delete originals or choose a lost-device recovery policy. This is data-copy/rehydration acceptance, not permission to activate these files as production state.

Source: `/home/ibkr/.local/state/openclaw/backups/20261109T234709.896409Z` on authenticated pinned host `ibkr-paper-test`. Existing backup timer is active; last service result success. This snapshot predates today's report and subsequent engineering changes.

| Source | Uncompressed bytes | SHA256 matches backup manifest | Read-only SQLite quick_check |
|---|---:|---|---|
| trading_audit.sqlite3 | 4554752 | PASS | ok |
| financial_ledger.sqlite3 | 126976 | PASS | ok |
| runtime/recovery.sqlite3 | 90849280 | PASS | ok |
| agent_secretary.sqlite3 | 35926016 | PASS | ok |

Mac archive SHA256: `2adabc02317433db0971f335d374958a2901a49bc352eece784695d96195f32a`. All archive/database copies are0600 inside a0700 owned directory outside Git. Decompression used explicit names, byte limits and exclusive destinations; SQLite was opened with mode=ro/query_only and a bounded progress deadline. Recovery snapshot still contains3STARTED/2UNKNOWN notifications. Nothing was cleared, retried or reclassified. No business rows/private conversations or database files enter this document or Git.

The separately copied Nov10 natural report1778 PNG/JSON/native receipt also passed exact queued hashes; see DAILY_REPORT_RECONCILIATION_20261110.md. Both original artifacts and this older database backup remain on Hetzner. Copies are on a second host, not independent encrypted/offline storage or all-device-loss recovery.

Private evidence: `~/.local/state/openclaw/engineering/goal-reconcile-20261110/four-db-backup-copy-receipt.json`; owned extraction directory and source tar are retained there. No test points at production DB/ledger. No live restore was exercised.

## Recovery and later phase gates

- The backup declares `cross_database_atomic=false`. Per-file SHA/quick_check cannot prove an aligned cross-database business checkpoint. Any future activation must preserve provenance and reconcile event/run/operation/outbox relationships, broker exposure and uncertain outcomes while maintenance is held.
- Current-state recovery-point age remains explicit. A successful old snapshot does not establish coverage of today's receipts, active model tasks or later order/risk state. No production snapshot is silently replaced by this copy.
- Continuous multi-device replication, interrupted-transfer resumption, conflict handling, recurring off-host backup verification and phone/iPad storage support remain NOT_IMPLEMENTED/NOT_VERIFIED. Mac is an additional copy here, never a prerequisite for cloud operation.
- Retention and cleanup remain separate: no deletion based on dates or filenames, and no automatic cleanup implied by successful copy.
- Future release approval must bind immutable commit, environment, operation summary, one-time validity and expiry. Passkey service/enrolment is not implemented or accepted by this data exercise; Telegram consent is not a substitute. No default freeze period or Telegram recovery bypass is selected.

No running service or dependency topology changed. Existing registered diagrams cover runtime owners; this manual verification does not add a daemon or imply a continuous synchronization edge. Source, offline testing, deployment and recovery acceptance remain distinct.
