# Four pillar history implementation plan

**Goal:** Persist separate session/API/market/cloud observations and transitions, and report rolling windows without fabricating past availability.

**Architecture:** Existing safety owner records callback-derived observations in its existing transaction. Existing host-status timer records cloud service observations in recovery.sqlite3. A read-only report exposes events and coverage gaps. No new broker, recovery, send or trading owner.

**Constraints:** Existing PAUSED/maintenance and closed Paper scope remain. Preserve unrelated external-heartbeat work. Full offline suite only in linked worktree; secret scan; Git integration; main smoke only.

**Files:** reporting/runtime_history.py (transaction-scoped persistence and evidence projection); trading/paper_safety_monitor.py (existing owner hook); ops/cloud/host_status.py (existing cloud sampler); ops/cloud/inspect_health_window.py (rolling report); tests/test_runtime_health_history.py.

**Review focus:** restart is an UNKNOWN boundary; missing samples remain UNKNOWN; history cannot substitute for real-time bars; stale callbacks cannot prove recovery; cloud self-observation cannot establish external alert delivery.

- [ ] Persist samples and changes, deduplicating unchanged states while preserving repeated occurrences and epoch boundaries.
- [ ] Test atomic recording, stale/history separation, rolling-window gaps and read-only behavior.
- [ ] Run full isolated suite and gitleaks; commit only intended files, integrate via Git, smoke, deploy with existing identities and single owners.
- [ ] Read back actual persisted rows; expose evidence/report in VS Code, explicitly retaining predeployment UNKNOWN history.
