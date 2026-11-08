# Resumed Paper goal implementation plan

User scope: finish all authorized work remaining from Nov7; resumed Nov8. No new chat archive. Only owner may search der robot messages and existing secretary work logs. No broker mutation, fault drill, quota reset or pause release.

- Add a pure API-heartbeat validator independent of upstream status; fresh upstream outages preserve their API socket, stale heartbeats follow the existing bounded reconnect policy.
- Add bounded on-demand search of existing secretary and notification records, with provenance, pagination and secret redaction; direct Python /work and /searchlog commands bypass inference and remain owner-private.
- Add a local Telegram user-session search adapter, restricted to the configured der group and known bot sender IDs. No start/login, sends, read receipts, downloads, update listener or message database. Missing dependency/auth remains explicit. Route model requests through the existing local bridge; session credentials never enter RPC or model context.
- Audit readiness, holdings/protection, intelligence, report delivery, audit-compaction evidence and upstream sources. Record exact user parameters and authentication boundaries; prepare only a draft performance T0.
- Full isolated offline suite and secret scan, commit in worktree and Git deployment. Preserve unrelated files, global gate hashes and Gateway owner. Verify live read-only search and monitoring evidence; no false successful Telegram history search without a session.
