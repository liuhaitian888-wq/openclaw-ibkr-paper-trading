# P0 execution admission Implementation Plan

> **For agentic workers:** Implement task-by-task in this linked worktree using the existing isolated test entry. User authorized direct execution; no additional plan approval is required.

**Goal:** Close independently repairable execution admission defects and produce a current, read-only P0 evidence bundle before any Paper release.

**Architecture:** Preserve existing TradingService, RiskEngine and autonomous runtime ownership. Reject invalid monetary inputs at risk admission; retain original quote timestamps through scanner serialization and runtime validation; stop a cycle on uncertain submission rather than attempting another entry. Existing monitor-only cloud strategy remains paused pending owner parameters and native acceptance.

**Tech Stack:** Python unittest, Git worktree, existing runtime/reporting modules.

**Spec:** docs/PAPER_ACTIVATION_CHECKLIST.md and user's prioritized P0 instruction.

## Global Constraints
- No change to PAUSED/MAINTENANCE, execution approval, real limits or existing orders.
- Complete offline suite only through scripts/run_worktree_tests.py in linked worktree; production only quick smoke.
- UNKNOWN/STARTED never automatically replayed; all resources have bounded lifecycle.
- Parameters already approved remain approved; newly needed parameters are requested once.

## Review Focus
- NaN/infinity/boolean or fractional quantity must never become an approved monetary proposal.
- Missing/naive/future/stale quote timestamp must never be replaced by current time.
- Crossed/missing/nonfinite bid/ask must not pass a session entry.
- Unknown submit result must stop remaining entries in the cycle and persist an accurate outcome.
- A read-only readiness result must not grant execution or equate offline testing with broker acceptance.

### Task 1: Harden risk inputs
Files: trading/risk.py; tests/test_risk.py.
- [x] Add tests for nonfinite monetary values, overflow, invalid quantities/sides and invalid exposure/limits.
- [x] Validate inputs before additive cap arithmetic and risk comparison.

### Task 2: Preserve quote provenance and stop uncertain cycles
Files: trading/strategy.py; trading/autonomous_runtime.py; tests/test_autonomous_runtime.py.
- [x] Serialize quote_timestamp from actual Quote; parse exact aware timestamp without fallback.
- [x] Reject invalid bid/ask and future/stale source evidence; no invented receive time.
- [x] Record PENDING/UNKNOWN and stop subsequent entries after uncertain/exception outcomes; no retry.
- [x] Exercise stale/future/missing timestamps and unknown/exception result before second event.

### Task 3: Validate and record P0 evidence
Files: docs/production-audit/P0_EXECUTION_20261108.md; ENGINEERING.md.
- [x] Save bounded cloud readiness/deployment facts, owner parameter candidate and remaining native acceptance cases.
- [x] Run full offline suite and gitleaks; commit and integrate through Git preserving unrelated work.
- [x] Main smoke and cloud read-only checks only; publish no execution manifest and start no strategy owner. Integration and deployment observations are appended to the closeout document.

## Nov9 delegated owner decisions

Owner explicitly delegated strategy and portfolio cap choices, requested QMAX100/OMAX2000 and nullable additive fields, authorized adding missing protection and a Telegram update. Preserve actual Paper identity and existing PFE stop. Currency display conversion is distinct from a cash-funded FX order. Adopt finite SMAX250000/GMAX1500000 USD as large ceilings, not target allocations; existing cash-only and per-order risk gates remain. Stop rules require fresh data and scoped, independently validated native transport; do not mark uncovered holdings protected based on authorization alone.

### Task4: Reflect the delegated numeric policy honestly
- [x] All five additive caps may be blank/null: no extra override, never removal of executable hard caps. UI and server agree; quantity remains integer when supplied.
- [x] Explicit CODEX_OWNER_CHAT numeric approval provenance bound to exact revision/settings, separate from native Telegram CONTROL_INSTRUCTION.
- [x] Update actual QMAX100/OMAX2000/RMAX10/SMAX250000/GMAX1500000 and hard quantity/order limits100/2000 through auditable deployment; keep execution paused.
- [x] Send one concise owner-only Telegram update through the existing outbox; verify native receipt.

### Task5: Monetary conversion and signal sizing
- [x] Reuse CashBook-style Decimal conversion via a common base currency, require timestamp/identity/positive finite rates; clearly label accounting conversion versus executable FX.
- [x] Candidate observer sizes integer BUY proposals under both quantity and money/risk ceilings, no forced100-share order. Preserve monitor-only mode.
- [x] Full isolated regression and secret scan, Git integration, bounded deployment/readback. Protection and native partial-fill acceptance remain separately audited.
