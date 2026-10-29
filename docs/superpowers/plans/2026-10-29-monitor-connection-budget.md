# Bound the existing Paper monitor connection loop

Evidence: existing per-symbol SubscriptionLifecycle bounds data subscriptions, but paper_safety_watch outer connection retry loop was infinite and reset its in-memory attempt counter immediately after subscribe. This invalidates a broader claim that all monitor recovery attempts were finite.

Minimal candidate: persist connection_recovery in existing paper_safety_state, owned by the same locked PaperSafetyMonitor. Reserve before socket creation, at most four attempts with 30/60/120/300-second backoff. Process restart or elapsed time alone cannot reset it. After exhaustion, only a different verified local Gateway PID/starttime plus elapsed cooldown admits a new finite episode. Missing process evidence never rearms. No Gateway process mutation. A complete identity/account/end-marker readback, fresh upstream heartbeat and at least 60 seconds on the connection are required to clear the episode; socket readiness alone is insufficient. This grants no market or trading readiness.

The sole watch loop continues bounded state publication while held; independent existing account readback and email owner remain. No extra subscriber, executor, store, controller or order action. It does not reset per-symbol subscription budgets.

Targeted TCP-disabled temporary-state tests: 36 PASS across connection budget, existing safety monitor and scoped system context. New tests cover restart persistence, same-condition hold, changed condition cooldown, missing Gateway evidence, incomplete/short/stale/identity-failed recovery. Gitleaks/diff checks PASS. Full suite not rerun per user instruction. Candidate only; no production deployment or forced reconnect. Sustained live recovery remains unverified.
