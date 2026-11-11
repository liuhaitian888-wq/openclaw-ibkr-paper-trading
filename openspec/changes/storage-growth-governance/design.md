## Context
Official SQLite/systemd/Python/restic sources were researched before implementation. Exact links and actual disk/target receipts are in docs/STORAGE_GOVERNANCE_20261111.md. Protected historical copies are not cleanup permission.

## Decisions
Opt-in nontrading storage-policy governs only PUBLIC_SCREENING/PUBLIC_DIRECTORY. Use8GiB and28percent floor plus run reserve, raw directory quota256/64MiB and per-blob5/2MiB. Incomplete50ms/2000entry inventory refuses optional writes. Store128-event/64KiB diagnostic ring; existing capacityowner observes OPTIONAL_STORAGE_WRITES via shared registry and exposes recorded decisions.

Local archive uses explicit public-only paths, default5GiB target cap and100GiB free floor, <=32paths and finite <=128MiB/60s batches. Content-hashed1MiB chunks and stable source metadata precede durable resume checkpoints. Transport read interruption is resumable; identity/checksum uncertainty requires reconciliation. Quarantine byte reconstruction is not financial/database restoration. No delete or automatic expiry API.

## Risks / Trade-offs
Public historical snapshots are provenance and not guaranteed reproducible; keep originals. Source/target filesystemI/O is not hard-real-time. This initial archive whitelist excludes historical bigDBs/credentials; Mac is optional and never a sole backup/core dependency. Optional research freshness may remainpaused until approved space/headroom resolves; do not lower thresholds to turn it green.

## Validation and Release
Full linked offline tests cover no core block, before-DB deferral, quotas, symlinks, blob bounds, prior-source preservation, partial/resume/dedup, checksum/source mutation and target limits. Actual261185byte two-batch public copy and independent source/localSHA plus quarantine reconstruction passed, source retained/reclaim0. Publisher separately validates combinedsource/config and observes actual producer deferral and secretary data; capacity first wave must not wait for this change.
