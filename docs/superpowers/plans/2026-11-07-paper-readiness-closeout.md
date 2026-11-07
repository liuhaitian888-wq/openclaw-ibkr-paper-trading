# Paper readiness closeout Implementation Plan

> **For agentic workers:** Execute natively under the user's explicit authorization; no delegation or approval handoff for read-only/reversible work.

**Goal:** Produce a reproducible execution-blocker report, evidence-backed holdings inventory, inactive performance baseline proposal, and current source/backup verification without enabling execution.

**Architecture:** Read existing authoritative state through bounded read-only SQLite snapshots; deterministic Telegram commands share this collector. T0 is a draft until execution and accounting coverage are approved. Existing production guard and order paths remain closed.

**Tech Stack:** Python standard library, SQLite, existing Telegram outbox and systemd owners.

**Spec:** User continuation 2026-11-07, items 1–9 and current request.

## Global Constraints
- Linked worktree development/full offline tests only; main workspace quick smoke only.
- Preserve PAUSED/MAINTENANCE, all existing orders and exhausted 3/3 test allowance.
- No fabricated ownership, account risk, fee/FX, price freshness or strategy approval.
- Existing archive and unreconciled evidence retained; no paid subscription.

## Review Focus
- Fresh identity with incomplete readback must fail readiness.
- Old quotes after close are not a network outage or real-time trading permission.
- Unprotected external holdings remain risk exposure, never adopted by a strategy.
- Missing/corrupt controls or unreadable operation ledger stay unknown/blocked.
- A successful model run without a research-scope tool call is incomplete configuration.

### Task 1: Deterministic readiness and holdings collector
**Files:** reporting/paper_readiness.py; reporting/secretary_controls.py; reporting/secretary_queue.py; trading/portfolio_exposure.py; trading/service.py; tests/test_paper_readiness.py; tests/test_secretary_controls.py.
- [ ] Add bounded read-only collector with separate account/readback, strategy/manifest, operator, protection, data, accounting and execution-acceptance checks; no permission grant.
- [ ] Add /ready and /holdings native owner controls, short factual messages and artifact provenance.
- [ ] Tests cover incomplete/stale broker state, preserved external holdings/orders, missing controls, unknown ledger and no side effects.

### Task 2: Source and archive closeout
**Files:** docs/INTELLIGENCE_RUNTIME.md; docs/INTELLIGENCE_SOURCES.json; docs/UPSTREAM_REPOSITORIES.json; docs/PAPER_ACTIVATION_CHECKLIST.md.
- [ ] Inspect actual source statuses and free-feed official contracts; bounded cloud probes only, no unverified install.
- [ ] Create fresh consistent backup; restore copies offline, verify decompressed hashes, integrity and retained row/schema equivalence.
- [ ] Save fresh database page, holdings and inactive T0 proposal in private state; do not replace live state during restore validation.
- [ ] Give autonomous research a bounded actual evidence context and verify scope tool result independently of run success.
- [ ] Verify Similarweb limited free tier and marketing UI; document any unavailable opt-out accurately.

### Task 3: Publish verified engineering and one owner decision sheet
- [ ] Full worktree suite and secret scan, commit, Git deployment and quick smoke.
- [ ] Resume only existing owners with current deployment identities.
- [ ] Recheck /ready, operational health and unchanged trade gate hashes; list exact user choices and separately unfinished engineering acceptance.

Implemented scope also adds fresh, complete external portfolio marks at the actual service risk entry when SMAX/GMAX are set; absent marks reject instead of assuming zero. BLS fallback uses fixed official monthly series with persisted six-hour per-series caching, retaining the RSS outage separately.

User steering added cash-only/no-overdraft boundary, actual Telegram report repair, and GPT/Codex communication. Implementation additionally covers trading/cash_guard.py at TradingService, Chinese font availability and measured report height, render revision invalidation and nonzero holdings count, and reporting/engineering_relay.py. Proposal storage does not grant infrastructure execution or wake this desktop chat automatically. Official SDK/MCP documentation distinguishes possible integrations from currently connected features.
