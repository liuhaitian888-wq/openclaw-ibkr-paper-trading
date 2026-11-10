# Secretary Python tools implementation plan

**Goal:** Telegram secretary invokes Python for live IBKR queries, all registered business DB queries, operations and Codex Cloud development tasks, with actual receipts and timing.
**Architecture:** Reuse cloud OAuth model, Telegram owners and the existing PaperSafetyClient broker connection. A durable per-run/step queue in the already-backed-up secretary DB carries broker queries; the existing broker loop alone owns subscriptions. An explicit operations registry exposes service inspections; Codex Cloud CLI dispatch records STARTED before submitting and never replays uncertain submissions.
**Spec:** openspec/changes/secretary-market-operations/specs/secretary-engineering-review/spec.md
**Constraints:** Linked worktree full offline suite; existing PAUSED/MAINTENANCE/UNKNOWN preserved; OAuth and broker auth separate; no production DB test targets; all resources closed by owner.

## Review focus
- Broker reconnect/late callback must not yield fresh current facts from another generation.
- Repeated tool identity must return original request/result, never trigger duplicate transport.
- Missing/unregistered DB and invalid paths must be explicit, never create files.
- Model-generated engineering text must not impersonate owner authority or deploy a patch.
- Unknown cloud submission and stale service evidence must survive restart honestly.

## Tasks
- [x] Implement reporting/secretary_broker.py queue plus trading/secretary_broker_owner.py, attach only to the existing paper_safety_watch owner; test real callback completion, mismatch, timeout, no replay and cleanup.
- [x] Extend ops/cloud/secretary_rpc.py and the model tool charter with live broker queries/results, explicit operations inspection, inventory and Codex Cloud task submit/status.
- [ ] Implement reporting/secretary_operations.py with fixed service/operation registry and official Codex Cloud CLI adapter; native owner scope and durable uncertain submission evidence; test injection/refusal/receipts.
- [x] Verify all four actual cloud DBs and explicit full path/source metadata, retain bounded SQL query and cross-DB consistency limits.
- [ ] Run supported full offline suite, strict specs, secrets; commit and Git integrate/deploy with current cloud lineage, update identity only after scope comparison.
- [ ] Observe actual broker response, Codex Cloud native task and Telegram request/result timing; mark missing owner request acceptance unverified.
- [ ] Update actual diagram and provenance with archify, closeout and independent five-project collector.

Progress evidence: source91f7f64 deployed; native broker query1.226s successful and systemctl/database probes accepted. Official Cloud adapter environment compatibility is unverified; server-hosted versus official executor intent clarification pending. Native Telegram result/latency and dev/ops write paths remain required for full goal.

## Measured optimization follow-up
Files: reporting/secretary_broker.py validates optional snapshot sections; trading/secretary_broker_owner.py returns selected fields and opens summary only for account/cash; scripts/run_secretary_bridge.py guides combined questions toward one snapshot. Tests: tests/test_secretary_broker_tools.py covers one reconciliation, selected-data projection, no account subscription for positions/orders and malformed/duplicate section refusal. Native before/after probes use distinct identities, existing sole model lock and original-result preservation; no Telegram impersonation/delivery claim.
