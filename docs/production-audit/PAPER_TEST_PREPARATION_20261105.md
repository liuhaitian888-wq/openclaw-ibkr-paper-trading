# Cloud Paper test preparation — 2026-11-05

This is a preparation checkpoint, not a successful order acceptance. User has authorized a separately bounded Paper test range. Existing global strategy limits and PAUSED/MAINTENANCE are not changed.

## Current facts

- Target remains exact configured Paper account DUQ503649, Gateway port4002, dedicated nonzero client IDs. Port4001 normally denotes Live and is not a concurrency fix.
- 10:25:00Z fresh readback complete, six positions, one existing PFE protective order, zero executions and zero local order_requests. Broker facts remain persisted from the Nov5 opening baseline.
- NVDA/AMZN/TSLA all returned 10197 and no valid bid/ask. Market-data type1 alone does not establish usable pricing. No new orders/cancels were sent.
- News historical retrieval is proven separately; streaming news, strategy signal interpretation and full provider coverage are not certified.

## Concrete next acceptance sequence

1. After the competing Live session ends, make one bounded quote/readback probe. Require exact Paper account, all snapshot end markers, valid fresh uncrossed bid/ask and no current10197. Persist times and errors; no blind retry of order outcomes.
2. Publish an explicit test manifest binding the approved cloud source SHA, account, dedicated test prefix/client and allowed contracts. Suggested initial scope: one share per order, USD1000 per order / USD3000 aggregate including existing exposure reservations under the test scope; no global limit edits. This scope is only a preparation proposal until the actual guarded executor and reservations validate it.
3. Validate durable intent/attempt journal, nextValidId, broker readback after restart, global existing/manual exposure and fees/FX reservations. Current production risk reservation work remains a blocker; an unimplemented limit must never be bypassed by marking health green.
4. LMT away from market: submit and observe broker acceptance, then cancel only that exact test-owned order and verify cancellation. Require orderId/permId/orderRef and precise request/ack/cancel timestamps.
5. Marketable LMT: observe actual execution/execId and position change. Pre-market use only broker-supported outsideRth limit behavior; no promise of fill. Reconcile first on timeout/UNKNOWN; never replay automatically.
6. STP/STP LMT and bracket/OCA coverage tests use only newly created test exposure and supported session rules; no naked stop can accidentally create a short. Do not touch existing PFE protection. Partial-fill, reject, cancel and recovery cases require distinct evidence; not every order type is fillable pre-market.
7. Close/reconcile only test-created exposure, verify no orphan test orders, retain event timestamps and full evidence; then assess remaining production acceptance separately.

No step above is claimed executed merely because API/news connectivity passes. Current status is BLOCKED_MARKET_DATA_10197 plus unapproved test executor/risk manifest; full production remains NOT_READY.

## Live logout recovery observation

User confirmed leaving the Live session. The first new Paper connection at 10:27:08Z still returned10197 for NVDA/AMZN/TSLA and no bid/ask, while account reconciliation remained complete. This proves detection but not recovery. Do not call a phone UI exit immediate server-side session release; preserve bounded observation and re-evaluate before any order.

API socket currently listens on wildcard4002, but UFW is active with default incoming deny and only22/tcp allowed (IPv4/IPv6); no public4002 rule. Diagnostics connect through local loopback. Gateway controller MainPID715454, NRestarts0 through this work. No Gateway restart was used to chase a green check.
