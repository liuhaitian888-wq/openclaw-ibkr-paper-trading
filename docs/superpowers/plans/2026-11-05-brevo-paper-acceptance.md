# Brevo fallback and cloud Paper acceptance Implementation Plan

> Execution: native in this linked worktree, within the user's existing authorization; no subagents.

**Goal:** Deliver original PNG reports through existing Brevo ownership while preserving uncertain outcomes, then establish evidence for scoped Paper order acceptance.
**Architecture:** Keep one durable notification outbox and one owner lock; select SMTP explicitly in the existing worker. Render local PNG without Feishu authentication, bind its hash in report manifests, and validate again before attachment. Trading gates stay independent.
**Tech Stack:** Python, SQLite, SMTP STARTTLS, systemd, IBKR Paper.
**Spec:** ENGINEERING.md and user instructions of 2026-11-05.

## Global Constraints
- UNKNOWN/STARTED never replay across transport changes. No historic flood.
- Exact Paper account, no changes to existing PFE protective order.
- Full offline suite only via scripts/run_worktree_tests.py; secret scan before commit; Git deployment.

## Review Focus
- Changed attachment content must fail before SMTP DATA.
- Switching transport must not resend accepted/uncertain notifications.
- SMTP confirmation must record send start/ack times.
- Feishu credentials must not be loaded for SMTP rendering.
- Restarts must retain one owner and bounded shutdown.

### Task 1: Original PNG via SMTP
- [ ] Extend financial_reports and report_schedule with explicit SMTP local-image readiness, preserving Feishu image-key checks.
- [ ] Extend incident_mail with hash-bound PNG attachments under a fixed report root, delivery timestamps and safe exception handling.
- [ ] Select transport in existing feishu_alert_watch; preserve queue identity, reminder/authentication scheduling and single owner.
- [ ] Add tests for PNG attachment, tamper rejection and UNKNOWN across restart; run full offline suite and secret scan.
- [ ] Commit only scoped files; Git integrate and deploy monitoring identity; switch one owner after inspecting queue; send one current report.

### Task 2: Gateway and order readiness evidence
- [ ] Read Gateway configuration and real restart/authentication logs without restarting it.
- [ ] Compare fresh account/position/order readback to canonical current state and source provenance; do not infer reconciliation from an empty new request table.
- [ ] Define separate test scope, quantities, maximum total exposure and supported order matrix; no unlimited automatic loop.
- [ ] Only after evidence-backed gates, run serial Paper LMT/STP/STP-LMT/bracket acceptance, retaining execution/cancel acknowledgements and cleaning only test-owned exposure.
