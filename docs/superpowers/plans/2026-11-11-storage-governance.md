# Storage growth controls and bounded local archive

**Goal:** Protect core state by withholding optional new research writes under capacity pressure; copy explicit public-source artifacts in bounded verified resumable local batches without deleting any source.

**Evidence:** SQLite WAL lifecycle, systemd keep-free/size budgets, Python bounded log handlers and restic structure-versus-read-data checks were researched before implementation. Exact links and current81%/6.83GiB evidence are in CAPACITY_RELEASE_20261111.md.

**Steps:**
1. Add a local disk/quota preflight for only two optional classes: broad-screening raw snapshots and public security-directory snapshots. Require an approved nontrading storage-policy document; preserve queued/UNKNOWN jobs and all core producers. Store a bounded diagnostic ring, not indefinite log lines.
2. Reuse existing capacity observer/shared health registry to expose the optional-write gate; add preflights before each optional producer starts network/DB work. No extra observer/daemon/sender.
3. Add an on-demand archive client: explicit public-artifact allowlist, no live/internal/history DBs, target5GiB cap/100GiB free floor, <=32paths, finite batches, content-hashed chunks, source-identity guards, resume/dedup and local quarantine restore verification. Mac is optional archive storage, never core-runtime or sole-backup dependency.
4. Add retention classification and dry-run-only cleanup report. No source deletion, no live SQLite maintenance, no old-backup cleanup or retention expiry. Critical financial/task/UNKNOWN/receipt state always protected.
5. Full linked offline suite, all-files gitleaks, strict specs and diagram/context maintenance. Demonstrate only a tiny authorized public-source batch with actual local headroom, interruption/resume, checksums and restore verification. Hand immutable SHA/config to the unique publisher for optional-write-gate deployment after the already-prioritized capacity observation release.

Root A integration: base actual409, combine d61 and268 only. After combined full/secret/spec gates, record fresh source/disk/gates/idle/unknowns; drain current model owner, stop only existing notification/inbox/OAuth owners, FF through Git with identity-only manifests and retained bounded backups. Arm exact0600 template; existing two optional public oneshots must DEFER before DB/network. Reload same three owners, release owned drain, verify natural edit on296 without repin and one new native budget query/result. Preserve Paper/Gateway and all prior scopes. B remains separate.
