## Context
Official SQLite/systemd/Python/restic sources were researched before implementation. Exact links and actual disk/target receipts are in docs/STORAGE_GOVERNANCE_20261111.md. Protected historical copies are not cleanup permission.

## Decisions
Initial opt-in nontrading storage-policy governs PUBLIC_SCREENING/PUBLIC_DIRECTORY. Use8GiB and28percent floor plus run reserve, raw directory quota256/64MiB and per-blob5/2MiB. Incomplete50ms/2000entry inventory refuses optional writes. Store128-event/64KiB diagnostic ring; existing capacityowner observes OPTIONAL_STORAGE_WRITES via shared registry and exposes recorded decisions.

Local archive uses explicit public-only paths, default5GiB target cap and100GiB free floor, <=32paths and finite <=128MiB/60s batches. Content-hashed1MiB chunks and stable source metadata precede durable resume checkpoints. Transport read interruption is resumable; identity/checksum uncertainty requires reconciliation. Quarantine byte reconstruction is not financial/database restoration. No delete or automatic expiry API.

## Risks / Trade-offs
Public historical snapshots are provenance and not guaranteed reproducible; keep originals. Source/target filesystemI/O is not hard-real-time. This initial archive whitelist excludes historical bigDBs/credentials; Mac is optional and never a sole backup/core dependency. Optional research freshness may remainpaused until approved space/headroom resolves; do not lower thresholds to turn it green.

## Validation and Release
Full linked offline tests cover no core block, before-DB deferral, quotas, symlinks, blob bounds, prior-source preservation, partial/resume/dedup, checksum/source mutation and target limits. Actual261185byte two-batch public copy and independent source/localSHA plus quarantine reconstruction passed, source retained/reclaim0. Publisher separately validates combinedsource/config and observes actual producer deferral and secretary data; capacity first wave must not wait for this change.

## B1 candidate: actual engineering artifact writers
Runtime3534da19 on actual7f adds engineering_preflight at run_once before reserve/canary/source/model; prepare rechecks before mkdir. Approved policy uses128MiB reserve/512MiB development quota, metadata20kentries/50ms. Existing STARTED/UNKNOWN reconciliation occurs first. Guarded Git child files are capped32MiB; source preparation4*tar+8MiB is an estimate, not a filesystem-wide hard quota. Original public classes and financial backups remain unchanged.

Publication CLI statically accounts mandatory recovery+secretary backup sizes, twice input bytes for upload/fetch, source bundle, extras and8MiB overhead. It requires<=256MiB plus originalpeak and2GiB postreserve; the owner must bind the real out-of-repository scripts before any corresponding copy. This is not universal control over all file writers. Content-addressed archive reuse is a separate C candidate, not B1 implemented behavior.
