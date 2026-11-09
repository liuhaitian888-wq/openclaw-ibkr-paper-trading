# Native Cash and Settlement Owner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish fresh native currency cash and settlement evidence from the existing read-only Paper safety owner, without any order path or new long-running process.

**Architecture:** One bounded accountUpdateMulti request at a time runs on the existing SDK client/worker after complete native reconciliation. Owned callbacks build a cashbook and retain the exact settlement receipt, cancel their own subscription and publish atomically; shared health distinguishes fact availability from permission to spend. The finite FX adapter retains its own receipts but does not compete with an approved continuous cashbook writer.

**Tech Stack:** Existing official ibapi1051.1, Python stdlib Decimal/zoneinfo/atomic files, existing CashBook/parser and shared reporting.health/RecoveryCoordinator.

**Spec:** `openspec/changes/p0-paper-execution/specs/paper-execution-p0/spec.md`, tasks5.2/5.3; `docs/production-audit/CONTINUOUS_ENTRY_20261109.md`.

## Global Constraints

- PAPER DUQ503649 only; PAUSED/MAINTENANCE/SAFE_MONITOR_ONLY remain; source is approved main workspace, persistent state stays under canonical root.
- Complete offline suite only in the linked worktree with `python scripts/run_worktree_tests.py`; production main runs quick smoke only.
- No BUY/SELL/cancel-order capability, new process, new worker, forced session takeover, subscription purchase or UNKNOWN replay.
- One accountUpdateMulti request, timeout8s, refresh no faster than5s; own request/end/cancel only; rows<=128, evidence<=90000UTF-8 bytes.
- Book and settlement freshness remain<=10s; a completed RPC is not proof of economic cash accounting or settled funds.
- Keep former source/evidence backup before native activation; preserve spent FX and protective scope IDs, budgets, outcomes and original expiry.

## Review Focus

1. Foreign or late callbacks must not fill an owned request or publish stale-generation cash.
2. Timeout, send/cancel exception and shutdown must not leave a second active subscription or worker.
3. Missing currency, accountReady=false, inconsistent duplicate values and overlarge payloads must not overwrite the last book or grant entry permission.
4. A new execution/fee or disconnect during collection must reject stale publication; exact source snapshots remain available in the audit of admitted claims.
5. Legacy FX completion must retain its native receipt while leaving the approved continuous writer's latest book intact.

---

### Task 1: Bounded callback collector

**Files:** Create `trading/native_cash_collector.py`; test `tests/test_native_cash_collector.py`.

**Interfaces:** `NativeCashCollector(client, account, connection_generation, admitted, publish, observe, clock, monotonic)` exposes `poll()`, `value(req_id, account, model, key, value, currency)`, `end(req_id)`, `close()`. It consumes existing `cashbook(values, account)` and `settlement_book(receipt, account=...,base_currency=...,as_of_day=...)`; it produces a BROKER_API book with exact native settlement_receipt and aware read start/end/observed timestamps.

- [x] Add tests asserting single outstanding request, exact callback identity, cancellation before publication, request timeout and shutdown, malformed/duplicate/oversized fields, missing USD, negative settlement retained as facts and publisher failure.
- [x] Run complete isolated entry;1107 tests/82.324s/one expected ModuleNotFoundError before implementation.
- [x] Implement the collector with no new thread, no order methods and bounded cancellation/failure state; callback errors do not kill the SDK worker silently.
- [x] Full isolated1117/75.759s/OK; gitleaks/OpenSpec checks and callback unit commit recorded in Git.

### Task 2: Existing owner integration and immutable publication

**Files:** Create `trading/native_cash_publication.py`; modify `trading/paper_safety_client.py`, `ops/cloud/paper_safety_watch.py`, `trading/entry_admission.py`, `reporting/health.py`; extend collector tests and shared health tests.

**Interfaces:** Optional client constructor `cashbook_publisher=None` leaves legacy behavior disabled. SDK callbacks delegate only owned accountUpdateMulti requests. `poll_cashbook()` is called by the existing service loop; `close_cashbook()` precedes SDK disconnect. Approved opt-in is `runtime/monitoring-deployment.json.native_cashbook_observation_approved=true`, never a production.json or trading release change. `publish_native_cashbook(root, monitor, book)` checks complete current identity/generation and execution/fee ordering, fsyncs an atomic private file and records only compact health metadata, not every full snapshot in callback history.

- [x] Add tests: default no request; opt-in delegates exact ID; changed native state rejects publication; atomic write leaves old target intact on failure; per-request resources close; repeated polling retains bounded FD/thread counts.
- [x] Add opt-in CURRENCY_BOOK in shared dependency registry before ORDER_SUBMISSION; freshness10s; dynamic ORDER_SUBMISSION dependency only when enabled. Negative balances can be healthy data without becoming spend permission.
- [x] Retain full admitted baseline cashbook in its once-per-intent audit claim; repeated polls do not create unbounded full-snapshot archive rows.
- [x] Full isolated1130/75.179s/OK; independent static review found no actionable regression; secrets/OpenSpec and owner integration commit recorded in Git.

### Task 3: Stop competing latest-book writers and verify native deployment

**Files:** Modify `ops/cloud/cash_conversion.py`, relevant tests, P0 docs/tasks/context.

**Interfaces:** Completed finite FX retains result/native receipt as before; when continuous cashbook owner is approved, it does not overwrite `runtime/currency-book.latest.json`. Existing legacy behavior remains when opt-in is absent.

- [x] Pin finite/continuous writer separation and private legacy file ownership; included in1130 isolated tests.
- [x] Commit and Git-integrate into main; quick smoke only, preserve unrelated files. Before any cloud integration, review additive schema changes on an isolated backup, exact identity files and unchanged order/permission boundaries.
- [x] Native opt-in only after verified code and source backup; use the same monitor owner, bounded shutdown and fresh exact Paper cash/settlement callback proof. Do not restart a healthy Gateway or enable API/strategy.
- [x] Verify newest file/health timestamps, positive ordinary versus negative settled USD, no new order/FX operation, preserved six stops and spent scopes; archive receipts and update P0 tasks without claiming whole strategy READY.

Native deployment217ac9070b46d4115fd674bdc241335436234856 accepted2026-11-09T22:13:57Z: current exact generation, six protected stocks, orders9/executions3/protection5/FX1 unchanged, GatewayPID2406467 unchanged during deployment. CURRENCY_BOOK raw HEALTHY remains resolved WAITING_DEPENDENCY: ACCOUNT/EXECUTIONS/AUDIT factual bridge is separate remaining P0. Release outbox1202 TELEGRAM_ACCEPTED; phone display unverified. Review correction: repeated publication failures could accumulate private partials; follow-up adds monitor-owned latch across automatic client replacement and separate obsolete-frame rejection. Explicit local persistence recovery and service restart required to clear a fault latch; no SDK/Gateway reconnect is triggered by this fault.

Follow-up validation: full isolated1130 tests/80.924s/OK, FD5 and recoveryFD4/thread1→1; strict OpenSpec5/5 and gitleaks passed. Native deployed217ac90 remains unchanged while this local fault-latch patch is reviewed and integrated. Initial new retry assertion used accumulated fractional fake time and failed; corrected deterministic fixture timestamp, then reran the complete suite.
