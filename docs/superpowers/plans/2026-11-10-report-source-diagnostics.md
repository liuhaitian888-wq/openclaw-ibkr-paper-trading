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
