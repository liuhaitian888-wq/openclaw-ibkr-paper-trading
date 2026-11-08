## Decisions
Reuse RiskEngine, canonical audit, RecoveryCoordinator, existing notification owner, pinned ib_async and CashBook-style Decimal units. New order scopes bind account, code identity, finite budget and preserved global gate hashes. UNKNOWN/STARTED never replay. Hypothetical fee requests are explicitly what-if; a reference conversion is not a real currency exchange.

## Boundaries
Source, isolated offline verification, cloud deployment and native acceptance are independent evidence classes. Legacy protection uses the existing temporary5% Paper fallback on fresh bid with actual broker tick. A new entry cap is not applied to leave inherited NIO200 partly uncovered. FX spends only existing EUR cash, covers the inherited USD deficit and leaves2010USD operating buffer; total EUR debit including fee reserve<=65000, one occurrence. Actual fees/positions/cash/executions must reconcile after fill. Funding conversion is excluded from stock daily notional and strategy return attribution.

## Diagrams
Registered .der maintenance boundary diagram concerns historical/cloud engineering maintenance and task completion; this patch does not change that workflow. New business paths are specified here and SCOPED_PROTECTION_20261109.md. Existing untracked output/archify artifacts are preserved, not represented as regenerated or verified against these paths.
