# Report source diagnostics Implementation Plan

> **For agentic workers:** Implement natively in this authorized session; no additional execution-method approval is needed under the user's direct-execution instruction.

**Goal:** Preserve exact safe reason codes for future SOURCE_UNVERIFIED builder outcomes without relaxing readiness or replaying historical sends.

**Architecture:** Evaluate the existing six source predicates in the builder. Return only fixed reason codes, parsed timestamp, age, and a canonical observation SHA256 to the existing journal owner; no new worker, DB, network or dependency.

**Tech Stack:** Python standard library, existing isolated unittest runner.

**Spec:** openspec/specs/secretary-engineering-review/spec.md, report provenance requirement.

## Global Constraints

Preserve PAUSED/MAINTENANCE and UNKNOWN. No report resend, new sender, model call, broker call or extra API fee. No account values or raw source strings in diagnostic output.

## Review Focus

Naive current time rejects without arithmetic exceptions; invalid source timestamp differs from stale time; future snapshot rejects; several failures retain all codes; evidence fingerprint is deterministic and contains no source fields.

### Task 1: Builder evidence

Files: reporting/financial_reports.py; tests/test_financial_builder.py; existing current spec and active secretary delta; .der/context/task-closeout.md.

Interface: source_diagnostics(observation, expected_account, now) returns reason_codes, source_snapshot_at, age_seconds and snapshot_sha256. prepare_reports retains existing status/prepared contract and adds source_check on rejection.

- [x] Add regression tests for each existing rejection predicate, combined failures, naive/future times, deterministic fingerprints and no report publication on failure; show initial failure.
- [x] Implement fixed reason codes with the same 600-second boundary; run prescribed complete isolated suite using existing .venv313.
- [ ] Update current/delta provenance requirement and evidence record, run strict specs and all-files gitleaks, commit/push task branch.
- [ ] Re-read concurrent cloud HEAD/manifests, back up config/manifest and consistent state, integrate only reviewed code via Git, run production quick smoke; restart only builder if required (oneshot next invocation otherwise).

Verification: main candidate1299/52.482s and exact cloud candidate1268/54.920s complete offline PASS; runtime698b44c/cloud1218579. Secret scansPASS; current/delta strictspec8/8PASS. Publication remains one unified team owner; no runtime deployment is claimed. No services need restarting for this oneshot builder import.

### Task 2: Preserve the successful report's original parsed observation

Scope: financial_reports.py writes a private atomically replaced `<TYPE>.SOURCE.json` sidecar for only the current preview. New manifest binds canonical-json-v1 bytes and safe source_check. Cache reuse requires that sidecar hash. report_schedule.py verifies new manifests' exact path/hash/account/environment/completeness/time and freezes the sidecar only when enqueueing, using the existing immutable archive/backup owner. Old manifests without this new optional contract retain explicitly marked legacy provenance; no historical source is fabricated.

No per-builder immutable source growth: mutable preview is overwritten; only queued sources enter content-addressed storage. No new producer/sender/dependency/permission and no historical replay. Regression tests use real isolated SQLite/temp files: observer changes after build, sidecar changes before/after enqueue, source tampering, cache upgrade and private atomic writes. Validate complete offline suite/secret/spec before handing the separate source commit to the unified publisher.
