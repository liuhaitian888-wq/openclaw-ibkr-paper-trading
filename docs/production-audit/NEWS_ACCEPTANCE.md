# IBKR news acceptance — 2026-11-05

## Implementation

Repository: https://github.com/ib-api-reloaded/ib_async, BSD licensed. Reviewed upstream `ab629f34c1823ea4c1542f32f07377208a86bdfd`; adapter uses published `ib_async==2.1.0`, pinned in `ops/cloud/requirements-news.txt`. This is an existing IBKR API implementation including news, not a claim that a third party supplies independent news subscriptions.

Official entitlement reference: https://www.interactivebrokers.com/docs/tws-api/doc/news/providers . API provider discovery returns subscriptions for the logged-in username. Historical titles and article retrieval require separate request verification. A TWS news subscription/UI display does not establish API access. No paid subscriptions are purchased or changed by this integration.

`/opt/openclaw/news-venv/bin/python /opt/openclaw/app/ops/cloud/collect_news.py` performs one bounded Paper-only read under approved monitoring deployment and a kernel lock. It checks the exact configured account, uses a dedicated nonzero client ID, requests at most three historical titles per returned provider (up to ten), over two days, then one article each. Every request is bounded; owned connection disconnects on all exit paths. It does not request price snapshots, modify orders, send notifications or restart Gateway. No recurring service is installed.

Private evidence is stored under state `observations/news/` and `runtime/news.latest.json`; raw article body is not redistributed. Article type, byte length and SHA256 prove receipt. Headline publication time is retained separately from retrieval/completion time. The shared health registry has independent `NEWS` evidence and stale checks; network recovery cannot promote it automatically.

`news_usable` means a recent successful historical headline + body retrieval for at least one provider and the checked symbol. It does not mean every provider/symbol is available, real-time streaming was observed, or news-based strategy permission. `live_stream_verified` and `strategy_news_ready` remain false. Empty query windows, provider discovery, timeouts and explicit permission errors stay distinct, per provider.

Legacy local simulation defaults `NEWS_FIXTURE_ENABLED=false`; explicit fixture events carry `source_kind=FIXTURE`, `simulation_only=true`, `is_live=false`. Legacy interface-name reports now say NOT_EXECUTED. Broker evidence is displayed separately, never fed through fixture heuristics as validated strategy signals. Existing historical sample rows remain historical evidence, not retroactively converted into real news.

## Acceptance

Offline suite: 762 tests passed, including connection-only, empty/timeout, identity, expiry, fixture, exception cleanup and partial-provider failure cases. Initial cloud collection at 10:21:53–10:21:55Z discovered eight providers and obtained seven article bodies. It also exposed that ib_async generic datetime formatting does not match the current news API dashed date specification: old Briefing results were returned despite the intended two-day request. The adapter now passes only an explicit `yyyy-MM-dd HH:mm:ss` start (empty end, per IBKR docs) and rejects out-of-window/malformed publication timestamps while retaining returned evidence. Date format and old-headline rejection are regression tested. Naive returned news timestamps are compared on a UTC basis; strategy_news_ready remains false, so this assumption does not authorize event-driven trading. Corrected cloud evidence follows below. No trading permission follows from news readiness.

### Corrected cloud acceptance

At 2026-11-05T10:24:13–10:24:15Z, exact Paper identity and resolved NVDA conId were checked. Eight providers discovered:

| Provider | Actual result after publication-window validation |
| --- | --- |
| BRFG / BRFUPDN | Three returned old headlines each, all excluded; OUTSIDE_REQUESTED_WINDOW |
| DJ-N | Three accepted headlines; article body verified (1324 bytes) |
| DJ-RTA / DJ-RTE | One accepted headline each; two old results each excluded; article body verified (3589 bytes) |
| DJ-RTG / DJ-RTPRO | Three accepted headlines each; article body verified (1324 bytes) |
| DJNL | Empty result, NO_HEADLINES_IN_WINDOW; not labelled unsubscribed |

No explicit permission-denied response occurred for these requests. This proves scoped historical retrieval for five providers, not full-feed streaming, complete universe coverage or paid entitlement to unlisted providers. Raw evidence is private state `observations/news/` (timestamped immutable JSON for the run), with latest projection `runtime/news.latest.json`. No fixture headline or article body was inserted into this evidence. One-shot collector is installed and verified; no new recurring service is enabled.

Paper preparation at 10:25:00Z: complete account/positions/orders/executions/summary callbacks, six positions, one existing PFE order, no executions, zero local order_requests. All three requested stock quotes lacked valid bid/ask and returned 10197 (competing Live session). Consequently actual submission remains blocked even though news retrieval succeeds. Evidence: `runtime/paper-test-preparation.latest.json`. Preserve original protective order and UNKNOWN outcomes; do not solve concurrent market-data permissions by changing the API port.
