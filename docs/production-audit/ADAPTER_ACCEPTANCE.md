# Real adapter acceptance — NOT_READY

Baseline: `32b1509e78bd8218552c0081746269146543caa1`. Only existing health registry/coordinator and production callers were wired; no new state machine. 24 module bindings. A registered adapter is not proof that its dependency recovered.

Evidence directory: `/Users/nbhsbgnb/.local/state/openclaw/maintenance/20260908T192959/adapter-acceptance/`. `final-live-adapter-smoke.json` is a timestamped maintenance observation; `main-smoke.json` is the final production-workspace check. Do not reuse either as future permission.

| Module | Dependencies | Observation adapter | Recovery adapter | Sample state / blocker |
|---|---|---|---|---|
| NETWORK | local/none | TLS egress (verified TLS, owned socket) | Existing coordinator: reobserve/revalidate | HEALTHY: Fresh verified TLS egress; endpoint health remains separate |
| DATABASE | local/none | audit_write_probe (existing event_store, mode=rw) | Existing coordinator: reobserve/revalidate | DEGRADED: Recovery proof missing: connect; OperationalError: unable to open database file |
| LOCAL_STATE | DATABASE | existing recovery journal committed transaction | Existing coordinator: reobserve/revalidate | WAITING_DEPENDENCY: Dependency unavailable: DATABASE |
| AUDIT | DATABASE | audit_write_probe | Existing coordinator: reobserve/revalidate | WAITING_DEPENDENCY: Dependency unavailable: DATABASE |
| DIAGNOSTICS | local/none | production_diagnostics.process_snapshot | Existing coordinator: reobserve/revalidate | HEALTHY: Live owner process observation |
| REPORT_ARCHIVE | local/none | fixed reports directory readback | Existing coordinator: reobserve/revalidate | DEGRADED: Recovery proof missing: connect; Local report archive availability |
| IBKR_CONNECTION | NETWORK | live_observation.probe: handshake + server time | Existing coordinator: reobserve/revalidate | HEALTHY: Live IBKR end markers/account/market evidence |
| MARKET_DATA | IBKR_CONNECTION | live_observation.probe: live bid/ask + approved universe | Existing coordinator: reobserve/revalidate | DEGRADED: Recovery proof missing: connect; Missing approved account, complete readback or live quote evidence |
| ACCOUNT | IBKR_CONNECTION | live_observation.probe: managedAccounts + accountSummaryEnd + PnL | Existing coordinator: reobserve/revalidate | HEALTHY: Live IBKR end markers/account/market evidence |
| POSITIONS | ACCOUNT | live_observation.probe: positionEnd + account scope | Existing coordinator: reobserve/revalidate | HEALTHY: Live IBKR end markers/account/market evidence |
| ORDERS | ACCOUNT | live_observation.probe: openOrderEnd + account scope | Existing coordinator: reobserve/revalidate | HEALTHY: Live IBKR end markers/account/market evidence |
| EXECUTIONS | ACCOUNT | live_observation.probe: execDetailsEnd + account scope | Existing coordinator: reobserve/revalidate | HEALTHY: Live IBKR end markers/account/market evidence |
| FINANCIAL_LEDGER | DATABASE | formal financial SQLite observations account scope | Existing coordinator: reobserve/revalidate | WAITING_DEPENDENCY: Dependency unavailable: DATABASE |
| EVENT_STORE | DATABASE | existing event_store durable write | Existing coordinator: reobserve/revalidate | WAITING_DEPENDENCY: Dependency unavailable: DATABASE |
| CANONICAL_STATE | DATABASE | formal canonical projection + published reconciliation | Existing coordinator: reobserve/revalidate | WAITING_DEPENDENCY: Dependency unavailable: DATABASE |
| RISK | ACCOUNT, POSITIONS, ORDERS | live exposure + exact scoped ownership provenance | Existing coordinator: reobserve/revalidate | DEGRADED: Recovery proof missing: connect; FileNotFoundError: [Errno 2] No such file or directory: '/Users/nbhsbgnb/.local/state/openclaw/production.json' |
| STRATEGY | CANONICAL_STATE, MARKET_DATA, ACCOUNT, RISK, DATABASE | existing Mode9 current-cycle account/quote readiness | Existing coordinator: reobserve/revalidate | WAITING_DEPENDENCY: Dependency unavailable: CANONICAL_STATE, MARKET_DATA, RISK, DATABASE |
| ORDER_SUBMISSION | STRATEGY, ORDERS, EXECUTIONS | existing audit reconciliation + durable pending attempt readback | Existing coordinator: reobserve/revalidate | WAITING_DEPENDENCY: Dependency unavailable: STRATEGY |
| REPORT | DATABASE, CANONICAL_STATE, FINANCIAL_LEDGER | existing generation manifest/source/artifact hashes and freshness | Existing coordinator: reobserve/revalidate | WAITING_DEPENDENCY: Dependency unavailable: DATABASE, CANONICAL_STATE, FINANCIAL_LEDGER |
| FEISHU | NETWORK | sender credential files + freshly issued tenant token; webhook unverified | Existing coordinator: reobserve/revalidate | DEGRADED: Recovery proof missing: connect; App authentication refreshed; custom webhook acceptance has no read-only verification API |
| DELIVERY_LEDGER | local/none | existing delivery.json schema/status readback | Existing coordinator: reobserve/revalidate | DEGRADED: Recovery proof missing: connect; FileNotFoundError: [Errno 2] No such file or directory: '/Users/nbhsbgnb/.local/state/openclaw/delivery.json' |
| DELIVERY | REPORT, DELIVERY_LEDGER, FEISHU | existing ledger UNKNOWN/STARTED hold readback | Existing coordinator: reobserve/revalidate | WAITING_DEPENDENCY: Dependency unavailable: REPORT, DELIVERY_LEDGER, FEISHU |
| WATCHDOG | LOCAL_STATE | existing resource log freshness + live owner PID | Existing coordinator: reobserve/revalidate | WAITING_DEPENDENCY: Dependency unavailable: LOCAL_STATE |
| MANIFEST | LOCAL_STATE | published deployment identity + actual Git commit | Existing coordinator: reobserve/revalidate | WAITING_DEPENDENCY: Dependency unavailable: LOCAL_STATE |

## Acceptance boundaries

- IBKR transport/account readback: real dedicated PAPER connection; handshake, managed account, server time, summary/position/open-order/execution end markers, fresh quote callbacks. Per-phase evidence is retained in the existing recovery journal. This is not completed business reconciliation against the unpublished formal audit. Unknown attempts remain held; no absence-of-fill inference.
- Approved account/universe, ownership review references and reconciliation must come from the deployment manifest. Diagnostic `--expected-account`/`--symbols` do not approve production configuration. AAPL/PFE canary quotes do not prove the whole production universe.
- Feishu app authentication refreshed successfully after reading both existing sender credential files. No message/image upload occurred. Custom-webhook acceptance lacks a read-only proof and remains unverified; authentication alone never makes FEISHU HEALTHY.
- Local modules use their actual atomic read/write validation; network authentication phases do not apply to local files. Recovery does not create missing formal DBs, publish migration candidates, start services, change maintenance gates or replay business operations.
- Hard gates now test audit and state persistence before side effects. Audit/state failure invalidates dependent observations; database recovery alone cannot re-open order/delivery gates.
- UNKNOWN order transport injection confirms durable STARTED before callback, UNKNOWN after timeout, and duplicate identity refusal after restart. Existing persistent Feishu STARTED/UNKNOWN/SENT_ACCEPTED never resend.
- Historical PFE order was read back again and matched exact account/environment/permId/orderRef and SHA256-verified original repair source. SYSTEM_OWNED, mutation unauthorized. Review remains unpublished. Manual exposure is retained and cannot be modified automatically.
- Legacy broker order/execution upserts now reject account/environment/source/run/occurrence/permanent-identity collisions transactionally. They do not migrate schema or reinterpret LEGACY_SCOPE. Every submit family also rechecks the actual newly connected account against the approved manifest, rather than relying on an earlier healthy account observation. Historical data, AAPL/ABT gaps and original values were not rewritten.

## Real resources

`verified-real-lifecycle.jsonl`: 30 real streaming reconnect cycles plus 30 real account observation sessions. Post-close FD=4, threads=1, sockets=0; both worker and reader closed, 2 subscriptions cancelled per connection, no retained timers/SQLite handles. Cycle 18 has a 913-second wall-clock gap and incomplete callbacks; retained as a failure, with no inferred cause. Controlled rerun `controlled-real-lifecycle.jsonl`: all 30 complete account readbacks and streaming quote pairs, 220.4 seconds, maximum cycle 13.9 seconds, FD=4/threads=1/sockets=0 after every close. Original cycle 18 remains recorded; the controlled rerun does not erase it. `broker-readback-endurance.json`: 10 actual TwsPaperBroker readbacks, post-close FD=4/threads=1/sockets=0. Resource stability of these components does not certify a full Mode9 production soak.

## Remaining production blockers

Formal audit/financial/delivery files, current canonical/business reconciliation, report artifacts, approved deployment manifest/universe/ownership publication are absent. Existing main untracked audit/diagram artifacts are preserved; the clean deployment check is not waived. Production/watchdog remain stopped and PAUSED/MAINTENANCE. Webhook acceptance and complete production recovery/soak are unverified. This is not an external-only outage and must not be labelled CODE_READY_BUT_EXTERNAL_DEPENDENCY_UNAVAILABLE.

Worktree validation: 502 offline tests (including fault isolation, UNKNOWN holds, SQLite refusal and scoped identity collision regression); gitleaks passed before commit. Main runs smoke only.
