# Bounded Gateway hang recovery plan

**Goal:** Detect sustained local Gateway hangs and recover through the existing systemd owner without retry storms or changing trading permission.
**Architecture:** Every 30 seconds a fixed root supervisor delegates observation/state/notification to the ibkr user under the approved monitoring guard. The evaluator reserves one restart durably before the supervisor submits the fixed unit restart, then verifies a new generation plus fresh native and independent complete Paper readback. STARTED/unknown never replays.
**Spec:** Owner request Nov8: learn upstream recovery patterns and automatically clear hangs.
**Constraints:** Linked worktree/full offline tests/gitleaks/Git deploy; no fault injection, no healthy Gateway restart. Existing PAUSED/MAINTENANCE/quotas untouched. Explicit maintenance-compatible recovery policy, independent hold marker, one restart/24h, >=15 minute hang, >=2 independent failures. No password duplication or model decisions.

- [ ] Implement pure durable decisions, evidence collection and fixed supervisor with no order capabilities.
- [ ] Test healthy/upstream loss/weekend/auth/identity/stale evidence/real hang/unknown/budget/recovery paths offline.
- [ ] Deploy timer without restarting healthy Gateway; verify observed healthy state, manifests, unit identity and unchanged gates. Real future hang end-to-end remains pending until one occurs naturally.

Sources: IBKR TWS Gateway docs, QuantConnect/IBAutomater README, ib-api-reloaded/ib_async ibcontroller.py, IbcAlpha/IBC userguide. Use their layering idea, do not install another competing Gateway controller or copy their unconditional 1100 restart behavior.
