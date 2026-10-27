# Paper callback safety recovery — implementation and acceptance

2026-10-27. Scope: DUQ503649 only. No Live connection, order mutation, strategy/risk parameter changes or real SMTP in offline acceptance.

## Existing execution and stops

- `trading/tws_paper.py`: openOrder/orderStatus/execDetails callbacks and bounded client shutdown; AuditLog execution table has exec_id PRIMARY KEY and broker identity conflict checks. Existing submit connections close after acknowledgement; they are not continuous lifecycle monitors.
- `ConservativeTrendModule._exit_decision`: long stop threshold is entry_price * (1 - effective_config.stop_loss_pct); profit target and SMA reversal are separate existing exit rules. Class default stop_loss_pct=0.003; existing pool CLI default=0.0015. Neither reference value is a newly approved production parameter. No percentage was changed.
- Existing pool strategy sends limit entries; its stop decision is Python managed and depends on a running process/data/position state. Existing `submit_bracket` constructs a DAY LMT parent + attached GTC STP child using the proposal's stop_price (not a full take-profit three-leg bracket). Do not silently reroute strategies to brackets or invent proposal.stop_price. The caller must derive it from the same approved effective strategy configuration and obtain the existing order authorization.
- A native accepted stop can remain at the broker during agent/network loss, subject to broker/exchange rules. It cannot guarantee execution price or eliminate gaps. Attached children may remain held until the parent is fully filled; partial parent fills are conservatively UNKNOWN until active coverage is proven. No real child acceptance was tested in this change.

## Added implementation

- `PaperSafetyClient` subclasses existing callbacks, stores execution immediately through AuditLog, and requests all open orders, completed orders, executions and positions on reconnection. `PaperSafetyMonitor` stores raw state and incident evidence through the existing recovery SQLite/IncidentStore. Duplicate execIds are idempotent; conflicting payloads block. Fills arriving during snapshot require another complete readback. No missed callback is assumed recovered from connectivity alone.
- Four protection states: PROTECTED / PARTIALLY_PROTECTED / UNPROTECTED / PROTECTION_UNKNOWN. Count only exact account + stock contract ID + USD + side, broker status Submitted/PreSubmitted, positive permId, explicitly transmitted, broker remaining quantity and proven parent activation. Cancelled/Inactive/completed/untransmitted stops do not cover positions. Ambiguous OCA, overcoverage, short/non-USD/unknown contracts fail closed. Historical or external positions are never assigned strategy ownership. Until protection policy/ownership is reviewed, all nonzero positions are conservatively checked.
- Shared health modules PROTECTION and PAPER_SESSION gate STRATEGY; proof heartbeat expires after five seconds. Missing monitor evidence blocks, including after restart. Existing risk, order-operation UNKNOWN, manifest and audit gates still apply; this monitor grants no order authorization.
- On 10197: clear market recovery evidence, pause entries, retain order connection; retry only own data subscriptions after 30/60/120/300 seconds (capped at 300). No session takeover, login or Gateway restart. Recovery requires a new complete broker readback, protection, both live quote sides <=5 seconds old, and existing slow_window count of complete 60-second K-lines after the fault. Twelve contiguous valid 5-second TRADES bars form each complete minute; no partial/future bars count. Delayed/frozen/crossed/invalid quotes block. API loss makes protection and order completeness unknown.
- Protection incidents, order errors, prolonged collision (60-second operational alert threshold), handshake/auth-or-connection symptoms, failed readback and recovery use incident IDs and existing SMTP outbox. UNKNOWN -> confirmed UNPROTECTED produces a deduplicated state-change notification. RED messages have high-priority mail headers, symbol/quantity/status/action. Delivery uncertainty is never replayed.
- Optional background SMTP owner polls at one second and is separate from broker callbacks, using the same sender lock and armed flag. Keep the old email timer disabled while this owner runs. SMTP headers request priority; acceptance does not prove Outlook delivery. External existing Healthchecks host/Paper heartbeats remain independent; no new check registration or URL changes.

## Deployment prerequisites (not yet met)

`ops/cloud/paper_safety_watch.py` is opt-in, with a disabled-by-default systemd unit. It requires published formal audit/recovery DBs, approved monitoring identity and existing production manifest containing exact Paper account, market_symbols and `strategy_configuration` with approved=true, bar_seconds=60 and the actual effective slow_window. Private `paper-safety.json` (0600) must contain matching account, environment=PAPER and symbols. These are verification requirements, not instructions to invent approvals.

The service owns one loopback:4002 API connection (clientId18770), its subscriptions, callback worker and SMTP worker; stops boundedly. No broker placeOrder/cancelOrder/globalCancel invocation exists in the monitor path. Existing submitter code remains separate and protected. The service does not persist/automate IBKR login credentials or bypass 2FA.

Formal databases/manifest are still unpublished in Hetzner. No monitoring service, SMTP flag, trading service or order was activated by this change. Existing epoch staging changes from the preceding task remain separate and uncommitted. Continuous on-host recovery, real protection acceptance and real alert/recovery delivery remain NOT VERIFIED. A missing monitor heartbeat blocks new strategy work but cannot guarantee delivery if the host, SMTP or network is down; external monitoring covers host loss.

## Official references

- https://www.interactivebrokers.com/docs/tws-api/doc/orders/place-order/introduction
- https://interactivebrokers.github.io/tws-api/order_submission.html (duplicate status, execDetails, attaching orders)
- https://www.interactivebrokers.com/docs/tws-api/doc/error-handling/error-codes

## Offline verification

See tests/test_paper_safety_monitor.py: native acceptance evidence, untransmitted/rejected/cancelled/missing stops, partial fills, duplicate/conflicting execId, parent held/OCA/contract ambiguity, disconnect/restart/incomplete snapshot, 10197 bounded retry, stale/delayed/crossed data, full K-lines, incident dedup/recovery, high-priority mock SMTP, shared gate expiration and actual callback adapter. Complete suite and final commit results are recorded in the implementation progress report.
