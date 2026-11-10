# Native prewire identity and final admission plan

Goal: prevent a broker connection/qualification delay from bypassing revoked gates, retain exact native order identities before the first opaque placeOrder, and reconcile lost acknowledgements without replay. PAPER only; existing PAUSED/MAINTENANCE, scopes and budgets stay unchanged. This is engineering, not formal release.

Architecture: keep the read-only monitor read-only. The existing dedicated financial owner must prepare a typed qualified contract, actual market-rule price increments and intended parent/stop IDs on its own SDK connection; persist immutable preparation before opaque transport. A preparation proves intent only, never a broker acknowledgement, cancellation authority, partial-fill coverage or funding permission. Final admission must include current source/gates and the exact existing claim once rather than double-counting it.

## Tasks

- [ ] Add an immutable preparation journal tied to the exact reserved intent, Paper account, SDK client/connection, contract and parent/child IDs; reject native-ID reuse across intent occurrences. Preserve all prior data and unknown operation history.
- [ ] Collect actual native contract details and market-rule evidence after handshake, normalize prices using those rules and revalidate monetary/risk limits on the wire economics. No default-cent fallback for the funded path.
- [ ] Revalidate current gates, cash/settlement/fee/source freshness and portfolio risk immediately before opaque wire; own in-flight reservations are checked exactly once. Do not exempt arbitrary user-supplied identities from UNKNOWN guards.
- [ ] Persist the transport occurrence before each opaque native financial mutation; distinguish verified no-send from ACK lost, and never release or replay STARTED/UNKNOWN by relabeling status.
- [ ] Wire the dedicated financial owner to eligible signals only after the above; native partial-fill/protection/exit/restart acceptance and final strategy release remain separate required proof.
- [ ] Full linked-worktree suite, secret scan, immutable-patch review, additive schema shadow validation, Git integration and bounded native acceptance. No cloud deployment during the notification owner's reserved window.

## Evidence and known limits

TradingService currently latches TRANSPORT_STARTED before calling TwsPaperBroker; the broker connects and builds symbol/SMART orders afterward, with no final service risk/gate check at the first wire boundary. The broker decorator has another STARTED guard, so simply calling the same gate again would reject its own occurrence; any exclusion needs a bound current-owner capability, not an arbitrary identity string. Resource revalidation also must not reserve or subtract the same intent twice.

Current monitor conservatively refuses linked-stop coverage until parent statusFilled. Native partial-fill coverage has not been verified. [IBKR FIX manual](https://www.interactivebrokers.com/campus/wp-content/uploads/sites/2/2023/07/IBKR-FIX-Specification.pdf) describes proportional child activation, but that is FIX-specific and is not evidence that this deployed TWS socket path has the same observable contract. [TWS order-type notes](https://www.interactivebrokers.com/campus/?p=195739&post_type=ibkr-api-page) require checking supported combinations. The project must not infer socket partial-fill coverage from an example, API acceptance, PreSubmitted alone or another interface's manual. Broker GTC acceptance is not guaranteed execution price or around-the-clock protection.

## Source progress (2026-11-10)

The isolated preparation journal and nonzero consecutive bracket-ID guard are implemented. The journal checks the exact reserved cash claim, retains immutable typed evidence and both ID reservations atomically, verifies fingerprint/reservation integrity on read, and refuses transport-started occurrences. This is only the journal portion of task 1: the financial owner's native SDK collector and final wire admission are not connected. Schema installation remains explicit and inactive in production; shadow migration is still required before activation.

Linked-worktree suite: 1201 tests, 46.566 seconds, PASS; FD regression remained 5 and recovery threads 1 to 1. Native partial-fill acceptance, price normalization, owner capability, deployment and trading release remain pending.

Integration verification: rebased onto main 365e58d, preserving secretary broker polling and notification reconciliation health. Full isolated suite 1253 tests / 49.164s PASS; all-files gitleaks PASS; strict OpenSpec 8/8 PASS. This does not constitute native acceptance or trading activation.
