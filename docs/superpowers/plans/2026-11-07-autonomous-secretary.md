# Autonomous research secretary Implementation Plan

**Goal:** Run an owner-only der secretary that autonomously investigates registered databases without changing trading permissions.

**Architecture:** Local official Codex OAuth inference owner uses bounded SSH RPC to the approved cloud workspace. Cloud archives instructions/results, offers read-only SQL/tests and reuses the existing notification outbox/sender.

**Tech Stack:** Python, SQLite, official Codex CLI, existing python-telegram-bot, SSH, launchd.

**Spec:** User messages 2026-11-07: autonomous topics/tests and all-database reads; secretary manages ordinary research/model costs and reports explicit boundaries or risks; start after tests. Continuation scope includes provenance and backup coverage. User explicitly instructs direct execution, no repeated approval and no subagents.

## Global Constraints
- All development/full offline tests in existing linked worktree; main quick smoke only.
- Preserve PAUSED/MAINTENANCE, broker orders and monitor owners; no copied OAuth tokens.
- UNKNOWN/STARTED paid operations never replay automatically; no competing Telegram receiver.
- Explicit public provenance, fees and data applicability; no private model reasoning archive.

## Review Focus
- SQL injection/writes/path traversal: read authorizer, fixed database registry, deadlines and result limits.
- Anonymous/forwarded/bot/other-owner messages: reject; native update ID and durable cursor.
- Crash after archive commit before outbox insertion: unique idempotent reconciliation.
- Model subprocess timeout/tool execution: bounded child-group cleanup; model tools disabled.
- Backup coverage and source fidelity: secretary SQLite archive restore/hash test; no fabricated strategy backtests or upstream integration.

### Task 1: Database and experiment interface
- [x] Implement reporting/secretary_read.py: query(root,database,sql,parameters,limit,budget) and tool(root,request).
- [x] Add real SQLite tests for rejected writes, extensions, symlinks, recursive timeout and numerical hypothesis falsification.

### Task 2: Inbox and model owner
- [x] Implement reporting/secretary_queue.py, reporting/secretary_model.py, ops/cloud/secretary_rpc.py and scripts/run_secretary_bridge.py.
- [x] Test native owner admission, duplicate updates, standing authority, uncertain paid operations, bounded model execution, public-only output and outbox reconciliation.
- [x] Add optional secretary modules to shared health registry; extend backups and notification formatting.

### Task 3: Validation and deployment
- [ ] Run final full offline suite and gitleaks; commit only this task's files.
- [ ] Cherry-pick through Git into main workspace, quick smoke, bundle ff-only cloud deployment; update approved read-only identity manifests with preserved provenance.
- [ ] Install local single-owner launchd bridge, cloud read-only policy; verify inference, real read tools, autonomous result archive and native Telegram send receipt.
- [ ] Refresh database console and open report/logs visibly in VS Code; document real-owner input acceptance separately.

Execution was expressly authorized by the user. No additional approval gate or new worker for trading/monitoring is introduced.
