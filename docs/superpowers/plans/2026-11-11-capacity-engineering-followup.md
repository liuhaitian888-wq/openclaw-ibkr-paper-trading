# Capacity engineering follow-up implementation plan

Goal: persist each real severe capacity occurrence as one bounded SYSTEM engineering task without another sampler/sender, Stage A only; optional source snapshot controls are a separate B delivery.

Architecture: the existing capacity tick reconciles primary-key source event/outbox pairs into the existing secretary engineering queue. A fixed-size local cursor advances only after the destination transaction commits. Secretary reads and an operator CLI expose the queue; only an explicit host claim permits read-only diagnosis. No model/native task is automatically invoked.

Spec: `openspec/changes/capacity-engineering-followup/specs/capacity-engineering/spec.md`.

Constraints: actual cloud base6ad75f8; PAUSED/MAINTENANCE unchanged; no old notification replay, paid resources, financial/history deletion, new observer, services or execution authority. Original UNKNOWN/devscope untouched. <=8 source occurrences/tick, <=128 protected capacity tasks, <=4KiB cursor, <=12 displayed rows. Existing optional policy8GiB/28% remains.

Review focus: source/destination crash, source identity mutation, WARNING/recovery after severe, UNKNOWN claim replay, low-space new engineering work consuming its one-shot authority.

## Task 1 — persisted source event to claimable queue

Files: new `reporting/capacity_engineering.py`, `scripts/capacity_engineering.py`, `tests/test_capacity_engineering.py`; edit `reporting/capacity.py`, `reporting/engineering_relay.py`, `reporting/secretary_presentation.py`.

Interfaces: `reconcile(root) -> dict`, `read(root) -> dict`, `claim(root, task_id, fingerprint, owner) -> dict`, `finish(root, task_id, owner, outcome, summary) -> dict`. Only `QUEUED_READ_ONLY -> STARTED_READ_ONLY -> DIAGNOSED|UNKNOWN`, never UNKNOWN replay. Source identity `storage-capacity:<sequence>`; task identity `capacity-followup:<sequence>`, with exact source SHA separate from occurrence. Fixed numeric projection only, never arbitrary commands.

1. Add isolated tests for real transition, historical severe after recovery, duplicate/restart, crash after task commit, missing/mutated source evidence, max backlog/tasks, UNKNOWN and concurrent/changed claim, read-only tool/mailbox/work visibility; verify first run fails.
2. Implement bounded primary-key reconciliation and atomic task+SYSTEM event/status insertion, no notification writes. Read only existing DBs for queries; explicit connections close. Cursor failure does not erase committed source or existing tasks.
3. Wire reconciliation into original tick even when sampling is not due; expose status in `capacity` and existing engineering mailbox/work view. CLI list is RO; claim/finish only this class. A task is not a USER instruction or native model acceptance, and desktop wakeup remains false.
4. Full offline entry verifies behavior, not just hook execution.

## Separate B planning sketch — excluded from this A candidate

Files: `reporting/storage_policy.py`, `reporting/engineering_development.py`, `reporting/engineering_patch.py`, corresponding tests.

Interfaces: `engineering_decision(root) -> dict` and `engineering_preflight(root) -> dict`; existing enabled policy gates new snapshots before reserve/canary/network. Reserve128MiB, existing development-tree quota512MiB, bounded50ms/20000-entry usage. Per-source retained preparation estimate `4*tar_bytes+8MiB <=128MiB`; no shared writable hardlink cache.

1. Test insufficient space/class quota refuses before one-shot reserve, model/canary, task directory and source archive creation; original STARTED/UNKNOWN reconciliation remains before new-work gate.
2. Add a second pure guard in prepare before any job directory and enforce archive estimate before extraction. Missing policy keeps previous unarmed behavior. Do not change the two public classes or existing min-free guard.
3. Run `python scripts/run_worktree_tests.py` using project venv in this linked tree, all-files gitleaks, strict OpenSpec; no full tests on main/live state.

## Task 3 — reviewable release and real boundary

Update OpenSpec/tasks, affected architecture via archify, `.der/context/task-closeout.md`; classify source/offline/deployed/native separately. Commit immutable candidate after checks and give unique publisher paths/SHA, event key, claim boundary, snapshot refusal behavior. Publisher combines after Gateway window; accepts existing2016 as backfill without new alert/native attempt, proves queue row+secretary read+host claim read-only, preserves all UNKNOWN. Read existing cache receipt246.4MiB, do not repeat cleanup. Refresh five-project collector at authorized closeout. No empty proposal/commit or implicit DB migration activation.
