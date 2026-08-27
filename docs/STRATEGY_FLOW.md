# Strategy Flow

This document is the maintained flow chart for the modular pool strategy. Update
it whenever the stock universe, data feed, filter stack, strategy modules, or
execution gates change.

## Current Pool Strategy Flow

```mermaid
flowchart TD
    START["Start pool strategy module\nscripts/run_pool_strategy_module.py"]
    HEALTH["Read Trading API /health\nconfirm mode and allowed_symbols"]
    SYMBOLS["Load requested universe\n--symbols or DEFAULT_POOL"]
    VALUE["ValuePoolFilter\nvaluation + quality + demand + safety"]
    ALLOWED["Build module_allowed_symbols\nAPI allowlist + value-approved pool"]
    SOURCE["Build QuoteSource\nIBKR readonly or simulated scenario"]
    ROTATE["RotatingSymbolPool\nfixed-size next_batch()"]
    QUOTES["Request quotes for current batch\nsingle quote source per batch"]
    CACHE["InMemoryQuoteCache\nlatest quote by symbol"]
    BARS["BarBuilder + SymbolRingBuffers\n1-minute bars, bounded history"]
    MODULE["ConservativeTrendModule\nclassic_conservative_trend"]
    BUY_GATE["BUY gate\nallowed symbol + fresh quote + spread ok + cooldown ok\nfast SMA > slow SMA + price confirms"]
    SELL_GATE["SELL gate for owned symbol\nprofit target, stop loss, or trend loss"]
    SUBMIT["Submit order proposal\nvalidate / stage / paper endpoint"]
    AUDIT["Trading API safety gates\nrisk, token, TWS readiness, audit ledger"]
    REPORT["Write JSON report + dashboard\nreports/ + dashboard/pool_strategy_dashboard.html"]

    START --> HEALTH
    HEALTH --> SYMBOLS
    SYMBOLS --> VALUE
    VALUE --> ALLOWED
    ALLOWED --> SOURCE
    SOURCE --> ROTATE
    ROTATE --> QUOTES
    QUOTES --> CACHE
    QUOTES --> BARS
    BARS --> MODULE
    CACHE --> MODULE
    MODULE --> BUY_GATE
    MODULE --> SELL_GATE
    BUY_GATE --> SUBMIT
    SELL_GATE --> SUBMIT
    SUBMIT --> AUDIT
    AUDIT --> REPORT
    MODULE --> REPORT
```

## Current Logic

- The scanner does not open a separate long-lived channel per symbol. It rotates
  through the universe in fixed-size batches and asks one quote source for each
  batch.
- `InMemoryQuoteCache` keeps the latest quote per symbol.
- `SymbolRingBuffers` keeps bounded bar history per symbol, so memory stays
  stable as the universe grows.
- The first strategy module is `classic_conservative_trend`, a long-only paper
  module.
- BUY requires an approved symbol, fresh quote, acceptable spread, no cooldown,
  enough bar history, fast SMA above slow SMA, and price above slow SMA.
- SELL only follows an in-memory BUY position and triggers on profit target,
  stop loss, or fast SMA falling below slow SMA.

## Current Defaults

- Default pool: `AAPL,MSFT,AMD,INTC,KO,PFE,T,F`
- Default batch size: `3`
- Default module windows: fast `2`, slow `3`
- Default paper test quantity: `1`
- Default profit target: `0.15%`
- Default stop loss: `0.15%`
- Dashboard output: `dashboard/pool_strategy_dashboard.html`

## Market Data Permission Plan

For a broad US equity pool, keep these market data subscriptions active:

- `NYSE (Network A/CTA)(NP,L1)`
- `NYSE American, BATS, ARCA, IEX, and Regional Exchanges (Network B)(NP,L1)`
- `NASDAQ (Network C/UTP)(NP,L1)`

These three cover the practical first layer for US listed equities. Add options,
futures, OTC, or international exchanges only when a strategy module actually
uses those instruments.
