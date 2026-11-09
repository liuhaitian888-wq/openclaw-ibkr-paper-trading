# Existing-owner account health bridge

Goal: publish real base dependency observations from the approved read-only owner while retaining all financial permission gates. Current native CURRENCY_BOOK is real and fresh but its ACCOUNT/EXECUTIONS/AUDIT dependencies are not wired; this plan does not classify the system as READY.

Architecture: reuse the existing SDK connection, callback worker, monitor lock and RecoveryCoordinator. No generic recovery probe creating a second broker client, no new service or background worker, no zero-valued synthetic PnL, no conversion of socket or TLS success into trading permission. Dependency changes remain in reporting.health.

## Tasks

- [ ] Capture actual currentTime callback timestamp separately from local receipt time, bound to the native connection generation; test invalid, foreign/stale and reconnect facts.
- [ ] Collect full typed account evidence needed by existing ACCOUNT semantics: NetLiquidation, TotalCashValue, AvailableFunds, BuyingPower and a separately owned native PnL receipt. Reuse accountUpdateMulti but distinguish currency facts from complete account facts. Verify PnL protobuf field presence before accepting zero; cancel only the owned request and bound timeout/shutdown.
- [ ] Add a bounded local bridge on the existing owner loop. Use a real committed audit write probe and owned local persistence evidence on a controlled cadence, not every callback. Use actual verified TLS egress for NETWORK, not loopback API reachability. Bound elapsed time and avoid delaying pending subscriptions/heartbeats. Keep exact observation/event times and stale recovery semantics.
- [ ] Publish IBKR_CONNECTION/ACCOUNT/POSITIONS/ORDERS/EXECUTIONS only after exact native identity, finite required account values, owned PnL, complete end markers, current generation and fresh reconciliation; retain actual broker exposure and order-kind uncertainties. Do not claim RISK/CANONICAL_STATE, ownership or strategy authority from these base facts.
- [ ] Isolated full suite and secret scan, fresh static review, strict OpenSpec, Git integration preserving concurrent commits, main quick smoke. Native opt-in requires backups, exact manifests and unchanged financial gates/scopes/operations. Verify negative settled USD remains blocked, all six protective orders remain, no new SDK owner/worker/financial transport and bounded resources.

Remaining independent P0: prospective stock/fee value-date semantics, full financial account baseline, final execution owner prewire checks, partial-fill/native protection/restart acceptance, inherited attribution and exact formal release/T0. A green data dependency does not close these tasks.
