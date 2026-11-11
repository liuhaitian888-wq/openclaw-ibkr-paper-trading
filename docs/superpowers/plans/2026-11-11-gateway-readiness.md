# Gateway business readiness and operator notice

Goal: existing Gateway watchdog must report a sustained handshake-only failure through the existing group sender without authorizing a restart, login replay, or trade.

Scope: user Gateway repair request; root cause proven by native state and independent observer. Existing handshake guard remains correct. Source and live acceptance remain separate.

- [x] Add a pure persisted readiness episode, requiring fresh distinct independent failures and 15 minutes; direct recognized authentication evidence may require immediate operator attention. Missing evidence never becomes confirmed login failure.
- [x] Reuse GATEWAY_RECOVERY health and existing incident/outbox/grouped operations projection. Publish deterministic episode events idempotently after state persistence, so process interruption cannot silently lose an alert.
- [x] Close only after new native complete Paper evidence plus independent complete Paper readback, sustained across bounded samples for60 seconds. A new Java generation or systemctl success alone cannot close it.
- [x] Map exact existing automater result codes to sanitized operator phases. Expose requires_operator through existing health for the shared status publisher without exposing account/log/credentials or claiming phone verification is required.
- [ ] Run regression and prescribed complete isolated suite, gitleaks, OpenSpec; give sole publisher immutable commit. Preserve shared main work. No live Gateway action until coordinator resolves the pending specific restart authorization.
- [ ] Update existing specs/context, diagram impact and five-project collection, retaining live acceptance gaps.

Additional proven omission: the upstream early phone-confirmation event was filtered by the controller. Include its canonical fixed phase (no raw log), test real C# phase extraction without starting Gateway, and publish a new immutable linux-x64 build candidate. Release installation and pending live recovery remain distinct.
