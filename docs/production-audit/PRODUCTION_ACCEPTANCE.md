# Production Acceptance — NOT_READY

Evidence: `/Users/nbhsbgnb/.local/state/openclaw/maintenance/acceptance-20260909T034441Z`. Baseline main: `24dd0bbc14e8bd5c3ec2b3d5f379016fdf24e211`.

| Item | Result | Evidence / blocker |
|---|---|---|
| Formal state identity | PARTIAL | Fixed root `~/.local/state/openclaw`; no env path override. No approved production.json, audit DB, financial DB or delivery.json. Candidates are not production. |
| Schema/version/config | UNVERIFIED | Candidate integrity checks pass, but user_version=0 and no approved schema/deployment identity. Config defaults are not approval. |
| Current broker | READBACK PASS | DUQ503649/PAPER; 6 positions, 1 PFE open order, 0 executions returned in API scope. Empty execution response is not historical non-submission proof. |
| Bidirectional reconciliation | BLOCKED | Formal side absent. Candidate has 48 pending, 11 submitted-not-closed, 50 old FAILED; all 109 requests lack account in proposal. No broker_orders/executions/reconciliation_runs rows. |
| Candidate current state | BLOCKED | 138 canonical rows / 66 duplicate symbol groups; PFE flags both zero vs current protective order. Latest state wrappers include test/bootstrap/simulation and stale underlying data. No newest-timestamp shortcut. |
| Financial | BLOCKED | Candidate observations cover 2026-09-02 through 09-04; no formal current ledger. Historical values are not current balance conflicts or current truth. |
| Ownership | OBSERVED | PFE exact scoped permId/orderRef/source hash proves SYSTEM_OWNED; mutation unauthorized. No current manual/UNKNOWN order observed; legacy records remain unresolved/LEGACY_SCOPE. |
| Full recovery | NOT VERIFIED | Actual host Internet OFFLINE phase not exercised; no approved universe, formal refresh/reconciliation or completed downstream recovery. Existing fault tests are not real chain evidence. |
| Feishu receipt | NOT VERIFIED | Fresh app auth succeeds. No current message sent; no message/request ID or receiver readback. Historical accepted notifications are not delivered report proof. |
| Resource observation | BOUNDED PASS | 60 real streaming/readonly sessions, 666.1s, 59 streaming reconnects; post-close FD=4/thread=1/socket=0. RSS 26304–37728 KiB, final 26624 KiB; no sustained growth observed. All readers closed, no kills. Full Mode9 soak remains unverified. |
| Permissions | ALL FALSE | See final-smoke.json. No production start, order, cancellation or message send. |

## Three bounded gate corrections

- Preserve maintenance in `runtime/MAINTENANCE`; recognize legacy file markers, but never confuse the case-insensitive `maintenance/` evidence archive with a flag. Marker was created before code transition; PAUSED and archive retained.
- Hold all nonterminal/unverified order_request statuses, including legacy prefixed pending/submitted and old FAILED, rather than checking only generic UNKNOWN/STARTED/PENDING_CONFIRMATION. No historical status changed or terminal outcome guessed.
- Expire old diagnostics observations rather than presenting an exited worktree probe as current HEALTHY evidence.

506 offline tests passed in worktree. Secret scan required before commit. Main receives changes through Git and runs smoke/acceptance validation only.

## What remains

Publish no data until current projection, historical isolation/lineage, business reconciliation and rollback are approved. Keep historical gaps and original rows. Do not promote mixed candidate state or rewrite pending requests to make checks green. Full recovery requires real step evidence against the approved formal state. A one-off Feishu receiver acceptance test requires an explicit exception to the current no-send condition, a confirmed destination, a durable unique attempt, and receiver-side evidence; no automatic UNKNOWN retry. Full Mode9 production soak was not started under the current prohibition.
