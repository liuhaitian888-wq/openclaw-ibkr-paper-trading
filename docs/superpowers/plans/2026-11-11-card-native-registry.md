# Native facts and health registration status card plan

**Goal:** Display verified native Paper recovery separately from disabled or stale shared health registration, without implying trading readiness.
**Architecture:** The existing single card reads the same local SQLite and observer snapshot. Native facts require explicit expected Paper identity, current epoch and bounded independent observation times. Registry status is a separate fixed view and never changes any health state or gate.
**Spec:** secretary-market-operations / protection-recovery-notifications current-link-card requirement.

- [x] Reproduce fresh current native data with NATIVE_BROKER_SESSION disabled/ACCOUNT stale; retain native recovery and show the registration gap separately.
- [x] Separate current native proof, prior same-epoch complete observation and independent observer snapshot. Reject wrong account/environment/source/epoch, stale/future times and malformed data. Do not use heartbeat as account timestamp.
- [x] Keep single-card host registry, prewire current-state validation, no extra sender/pin/action or trading permission. Test stale/downgrade transitions and fixed safe rendering.
- [ ] Run prescribed full offline worktree suite, secret scan and strict specs, then hand immutable commit to sole publisher; cloud remains frozen until Gateway owner handback.

Exact frozen source:1429tests/56.563s/OK,10new+24existingfocusedPASS,strict9/9 and gitleaksPASS; independent staticreviewno newblockers. Production/native readback is still pending sole publisher.
