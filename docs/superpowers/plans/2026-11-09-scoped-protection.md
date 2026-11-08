# Scoped inherited Paper protection Implementation Plan

**Goal:** Automatically add only missing protective SELL stops for the five explicitly authorized inherited holdings, without enabling strategy entries or modifying existing orders.
**Spec:** User Nov9 standing instruction to add missing protection without another approval; docs/production-audit/P0_EXECUTION_20261108.md.
**Architecture:** A bounded systemd oneshot owns a dedicated kernel lock and <=5 non-overlapping quote snapshots. Exact Paper/code/state scope expires at next US close, with fixed per-symbol maximum legacy quantities and <=5 new orders. STOP policies use existing project's temporary5% fallback referenced to fresh bid, broker tick rounding, plain STP/GTC/RTH only. Missing live data/session returns WAIT with no reservation. Persistent STARTED/UNKNOWN never replay; order acceptance requires native acknowledgement and fresh readback. No cancellation API; PFE excluded. Global pause/maintenance hashes preserved under separately approved reduce-only scope.
**Tradeoffs:** Stop5% is a temporary Paper protection rule, not a calibrated strategy guarantee; price gaps can exceed stop price. General strategy remains paused; native first submission remains acceptance evidence, never claimed from offline tests.

- [x] Pure scope/session/coverage planner: exact account/contract/quantity; reject shorts/fractions/foreign currency, crossed/stale/delayed quote, other live sell, excess coverage; preserve any existing order.
- [x] Atomic audit intent and durable operation ledger; global uncertainty blocks before another order; repeated occurrence never replay.
- [x] Bounded existing ib_async news-venv adapter, client lifecycle/callback ownership, verified end markers and quotes, post-submit readback; no positions mutation/cancel endpoints.
- [x] Register module dependencies in reporting.health, disabled unless explicit observation enabled; never infer global READY.
- [x] Full isolated worktree tests/scan, Git integrate; publish exact scoped candidate with manifest backups and timer; first maintenance run must wait for regular session, orders0.
- [x] Owner-only Telegram handoff with real state and first native result through existing notification owner; no synthetic receipts.
