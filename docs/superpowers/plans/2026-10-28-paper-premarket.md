# Paper pre-market monitoring fixes Implementation Plan

**Goal:** Stop routine snapshot alert flapping; preserve fail-closed gates and handle 1101 data loss.
**Architecture:** Existing Socket API monitor and single outbox owner; no broker mutations.
**Tech Stack:** Python, SQLite, unittest, systemd.
**Spec:** User pre-market audit request, 2026-10-28.

- [ ] Add isolated regressions: repeated routine reconciliation causes no extra protection email; timeout/disconnect/new fill still alerts immediately; 1101 resubscribes once, 1102 does not.
- [ ] Minimal monitor routine-refresh notification guard (not permission guard), bounded 30s; record relevant raw IB errors; serialize data-loss resubscription in existing owner.
- [ ] Focused offline tests plus gitleaks; commit through production workspace. Back up production recovery/config; deploy monitor-only with unchanged trading controls.
- [ ] Persist official guarantees, unknowns, live snapshot results and test output. No T2/T3/manual steps or Gateway restart. Stop.
