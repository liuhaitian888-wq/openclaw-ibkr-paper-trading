# Data Feeds

The strategy framework uses a provider interface so market data sources can be
swapped without rewriting the strategy logic.

## Provider Pattern

All quote providers should return the same internal object:

```text
Quote(symbol, last, bid, ask, close, volume, timestamp, source)
```

The strategy should consume `Quote` and `Bar`, not vendor-specific responses.
This keeps the pipeline modular:

```text
Stooq / IBKR / future provider
-> QuoteSource
-> quote cache
-> bar builder
-> signal engine
-> risk filter
-> execution plan
```

## Large Universe Scanning

The strategy scanner is designed around one quote source, a rotating symbol
pool, a quote cache, and per-symbol ring buffers. It should not open a separate
long-lived channel for every ticker during early scale-out.

Current local path:

```text
RotatingSymbolPool
-> QuoteSource.get_quotes(current_batch)
-> InMemoryQuoteCache
-> BarBuilder
-> SymbolRingBuffers
-> MovingAverageSignalEngine
-> TacticalLongStrategy
```

Default simulations request all symbols each step to preserve the original
small-watchlist behavior. For a larger universe, set a fixed batch size and let
the scanner cycle through the pool:

```bash
.venv313/bin/python scripts/run_strategy_simulation.py --source simulated --symbols AAPL,MSFT,QQQ,SPY,NVDA,AMD --steps 12 --batch-size 2
```

The cache keeps the latest quote per symbol, while each symbol's ring buffer
keeps only a bounded bar history. Fast execution should read from this warm
cache rather than blocking on a fresh per-symbol quote request.

The first automatic module runner uses the same path and submits only through
the local Trading API:

```bash
.venv313/bin/python scripts/run_pool_strategy_module.py --mode validate --source simulated-scenario --symbols AAPL,MSFT,AMD,INTC,KO,PFE,T,F --steps 18 --batch-size 4
```

Use `--mode paper` only after entering `TRADE_LOCK`. The runner still uses the
API key, trade-session token, TWS readiness check, allowlist, quantity limit,
and max-order-value risk gate.

## Current Free Bootstrap Feed

`StooqDelayedQuoteSource` is the first keyless feed. In this environment it can
return browser-verification or 404 responses, so the project also includes
`YahooDelayedQuoteSource` as a free fallback for the dashboard and early
simulation flow.

These sources are not Level 1 market data and they are not NBBO. Treat them as
free delayed public polling sources for plumbing, dashboard, and simulation
only.

Allowed use:

- framework testing
- research-mode polling
- simulation
- proving the cache/bar/signal pipeline

Not allowed use:

- final fast execution
- tight spread decisions
- sub-second entry/exit
- assuming bid/ask quality

Security notes:

- It does not use IBKR credentials.
- It does not use an API key.
- It only downloads public CSV quote data.
- The main risk is data quality and availability, not account compromise.

## IBKR Free Data

IBKR says accounts include free real-time streaming data for US-listed stocks and
ETFs from Cboe One and IEX. This is non-consolidated data, so it does not show
the full NBBO across all US exchanges. IBKR also lists free delayed data where
available and 100 free snapshot quotes per month.

Practical meaning:

- Good enough to bootstrap an IBKR read-only stream.
- Better than delayed polling for strategy plumbing.
- Not the same as full consolidated NBBO.
- For serious US equity execution, consider paid Level 1 consolidated data once
  paper testing proves the strategy deserves it.

The project now has an `IbkrReadOnlyQuoteSource` and
`scripts/check_ibkr_quotes.py`. They only request market data and do not expose
order placement.

Use:

```bash
.venv313/bin/python scripts/diagnose_market_data_channels.py --symbols AAPL,MSFT,QQQ
.venv313/bin/python scripts/check_ibkr_quotes.py --symbols AAPL,MSFT,QQQ
```

Test the free/non-consolidated IEX path:

```bash
.venv313/bin/python scripts/check_ibkr_quotes.py --symbols AAPL,MSFT,QQQ --market-data-type 1 --exchange IEX
```

If real-time permissions are missing, test delayed mode:

```bash
.venv313/bin/python scripts/check_ibkr_quotes.py --symbols AAPL,MSFT,QQQ --market-data-type 3
```

The strategy dashboard can also use the same read-only source:

```bash
.venv313/bin/python scripts/generate_strategy_dashboard.py --source ibkr-readonly --symbols AAPL,MSFT,QQQ --steps 1 --ibkr-market-data-type 3 --output dashboard/ibkr_readonly_strategy_dashboard.html
```

For a simple file-based live view, regenerate the static dashboard on a timer:

```bash
.venv313/bin/python scripts/refresh_strategy_dashboard.py --source ibkr-readonly --symbols AAPL,MSFT,QQQ --steps 1 --interval-seconds 10 --output dashboard/live_strategy_dashboard.html
```

IBKR market data type values used here:

- `1`: real-time
- `3`: delayed
- `4`: delayed frozen

## NBBO

NBBO means National Best Bid and Offer. It is the best displayed bid and best
displayed ask aggregated across protected US exchanges. A single venue feed such
as IEX or Cboe One can be real-time, but it is not the full consolidated NBBO.

Practical meaning:

- Free non-consolidated data can be enough for early paper testing.
- Full NBBO is better for spread and slippage controls.
- Tight short-term strategies should eventually use consolidated Level 1 data or
  another approved source that exposes reliable bid/ask.

## Spread Control

Spread is:

```text
ask - bid
```

For a buy order, you usually pay near the ask. For a sell order, you usually
receive near the bid. A wide spread is an immediate hidden cost.

Example:

```text
bid = 100.00
ask = 100.10
spread = 0.10 = 0.10%
```

If a strategy targets 0.5%-1.0% profit, a wide spread can consume a meaningful
part of the edge. The tactical strategy currently blocks entries when spread is
too wide relative to price.

## Slippage

Slippage is the difference between the expected execution price and the actual
fill price.

Example:

```text
expected buy = 100.00
actual fill = 100.08
slippage = 0.08
```

Slippage can come from:

- fast price movement
- low liquidity
- wide spread
- delayed quotes
- after-hours trading
- marketable orders walking the book

Small tactical strategies must treat spread and slippage as first-class risk.

## Target Feed Roadmap

1. Use simulated quotes for deterministic tests.
2. Use Stooq/Yahoo delayed polling to prove external polling and parsing.
3. Add IBKR read-only stream for paper account quotes, positions, orders, and
   P&L.
4. Keep a warm quote cache with freshness timestamps.
5. Add paid or approved consolidated data only after paper testing shows a real
   need.

Final fast execution should read from the warm cache. It should not block on a
fresh external quote request.
