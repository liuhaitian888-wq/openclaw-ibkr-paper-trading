# Finite own-cash funding preparation

Prior owner authorization permits cash-funded currency conversion without new borrowing. Nov9 owner delegated numeric choices and requested2000USD entries. Existing USD deficit is69788.66, EUR cash1007456.40. A bounded candidate sells at most65000EUR **including5EUR fee reserve**, solely to cover that deficit plus2010USD working buffer. This is currency funding, not a65000EUR stock entry; stock OMAX remains2000USD. No strategy enablement or legacy order mutation.

Actual live read-only EURUSD contract12087792/CASH/IDEALPRO type1 quote was1.11450/1.11453 at2026-11-08T23:27Z. A distinct broker what-if at23:29Z estimated1.79496EUR commission, zero initial/maintenance margin changes for a candidate64431EUR limit1.11435. Those facts expire; they were not real orders or permanent execution prices. Actual action requires new quote, fresh USD+EUR cash and exact native fee estimate.

The existing cash helper conditionally requested EUR only when absent. Reusing a client after a fill could retain old EUR cash. It now always requests explicit USD and non-USD base ledger ends and cancels each subscription in finally. A base read failure cannot inherit cached positive cash.

New scope is one immutable cash-funding-20261109-v1:EURUSD occurrence. Canonical audit plus RecoveryCoordinator STARTED precede placement. Live tight quotes, broker session, positive cash/spend bound, no other uncertain/cash-pair order and preserved global gate hashes are mandatory. Native complete fill, execution/commission lineage, new dual-ledger cash deltas, unchanged inherited non-cash positions and no scoped active order are required for FILLED. Partial/pending/timeout is UNKNOWN and never automatically replayed. Actual FX fee must be known and within5EUR reserve; do not treat missing commission as0.

The strategy's daily20000USD notional ceiling excludes explicitly typed PAPER_CASH_CONVERSION funding; conversion is not strategy turnover/return. Source authority is the already approved cash-only/automatic_fx policy plus exact finite deployment scope. No new package, broker session takeover or blank global release.

Sources: IBKR FX pair definition https://www.interactivebrokers.com/docs/tws-api/contracts/fx-pairs and pinned ib_async whatIfOrderAsync API https://ib-api-reloaded.github.io/ib_async/api.html . CashBook design https://www.quantconnect.com/docs/v2/writing-algorithms/portfolio/cashbook . Funding result must be recorded separately from this preparation and offline tests.

Final isolated verification:1022 tests/44.125s/OK; source/base cache-failure, exact cash direction/caps/fee/freshness, one actual submit after durable reservation, immutable UNKNOWN across restart, funding exclusion from stock daily turnover and native scoped outcome/cash unit regressions. FD5 for300 cycles, endurance FD4/threads1->1. Shared reporting.health registers CASH_CONVERSION inactive by default; a completed funding event is not aggregate READY. OpenSpec strict validation passes; the P0 change remains active until native and continuous execution requirements are actually accepted.

Concurrent broad-screening integration preserved its health entries, code and context summaries. Final merged isolated verification1039 tests/44.349s/OK, FD bounded, all5 OpenSpec items strict PASS. No full production suite. Candidate funding execution still requires its exact deployment scope; an offline assertion does not create authority or report a fill.
Latest combined source including the approved scanner-owner attachment:1040 tests/42.961s/OK; all5 OpenSpec strict items pass. The FX action will not enable a scanner/timer or release entry gates.

## Native acceptance (2026-11-09 Berlin)

Cloud sourceb3d00e6. One SELL64414EUR LMT minimum1.11465USD/EUR, permId957281729, execId0000e215.6af0f839.01.01. Actual commission1.79496EUR. USD cash-69788.66 ->2019.4231; EUR1007456.40 ->943040.605. StatusFILLED in canonical audit and CONFIRMED operation. An independent client18996 reread both ledgers, all open orders and positions:0 CASH active orders,0 uncertain order operations, the same6 STK quantities and unchanged PFE8/STP23.01/permId911411084. Global stock pause/limits and legacy NVDA scope unchanged.

The broker now also reports a CASH EUR/USD trade position of-64414EUR. It is retained as an FX transaction/virtual-position fact, not erased or mistaken for a stock short or actual negative EUR cash. Actual EUR/USD cash balances are both positive. Full portfolio currency classification, fresh available/settled funding at entry and continuous strategy execution remain separate P0 work; this individual fill is not a global READY event or strategy return.

Evidence: local engineering/p0-execution-20261108/{funding-execution.json,funding-independent-readback.json,funding-deployment.json}; cloud runtime/cash-conversion.latest.json, canonical cash_conversion_attempts/order_requests and recovery operation record.
