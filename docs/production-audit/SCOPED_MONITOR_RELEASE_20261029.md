# Scoped pauses — monitor-only release

Projection source: readiness4875b02. Base production1dc94d1. Only existing paper_safety watch/client/monitor/observer, symbol_health and signal_scheduler plus their tests/docs are included. TradingService, broker guard, reporting permission resolver and Mode9 execution supervisor changes are excluded. No new process, timer, Gateway, order transport or runtime permission.

Frozen linked worktree suite683/57.885s PASS; TCP disabled and isolated temporary state. Source combined suite722/58.305s PASS and focused32 PASS; later Mode9 aggregate/account scheduling improvements are separate candidates. Scan and diff check PASS before release.

Pause projection: L1 symbol/input faults, L2 declared strategy-target dependencies, L3 independently untrusted systemic state or existing operator hold. No symbol-count threshold creates L3. Per-trade RESUME is emitted only after fresh type1 market data, complete contiguous minute evidence, complete account/order readback and risk verification. Existing historicalDataEnd evidence can satisfy K-lines without fabricated5-second callbacks. Pause records remain in the existing recoverySQLite callback journal with affected scope/reason/conditions and durable transition sequence.

Current monitor-only deployment has PAUSED/MAINTENANCE, kill=true/transmit=false and unapproved execution ownership/risk/authority. Those facts legitimately retain L3; they are not introduced because of10197 symbol count. Local10197 scope is still separately reported. All monitoring, independent account-only readback, alerts and bounded data recovery continue. Existing PFEorder1/perm911411084 is preserved.

Takeover: verify clean1dc94d1; stop only existing paper-safety; verify PID exit and kernel FLOCK release; back up manifests and full recoverySQLite. Fast-forward Git to this exact fixed commit; rebind monitor-only manifests retaining ready=false/grants_trading_permission=false. Start same unit, independently verify single new PID/FLOCK, exact Paper readback, preserved subscription budgets/PFE and unchanged GatewayPID. Existing market-session acceptance timer is unchanged. Do not rerun deployment on a short observation timeout; inspect the actual service.

Rollback: same single-owner procedure to1dc94d1 and matching monitor-only manifests; preserve current audit/recovery state/counters after data requests. No rollback to the older unlimited subscription owner. This release is not unattended Paper execution acceptance.
