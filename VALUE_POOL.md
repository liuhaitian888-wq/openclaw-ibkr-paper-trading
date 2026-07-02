# Value Pool

The value pool answers one question:

```text
Which symbols are good enough to be considered by short-term tactical logic?
```

It is not a buy signal. It is the first filter before moving-average signals,
spread checks, freshness checks, and risk controls.

## Core Idea

The pool should favor companies with:

- durable demand
- reasonable valuation
- positive earnings
- positive free cash flow
- acceptable debt
- enough liquidity
- improving or stable fundamentals

The tactical strategy may still enter and exit quickly, but it should only do so
inside a better-quality universe.

## First Metrics

Valuation:

- `pe_ratio`
- `forward_pe`
- `peg_ratio`
- `price_to_free_cash_flow`

Quality:

- `gross_margin`
- `operating_margin`
- `return_on_invested_capital`
- positive earnings
- positive free cash flow

Demand and growth:

- `revenue_growth_yoy`
- analyst revision direction
- later: backlog, bookings, user growth, segment growth, guidance changes

Safety and tradability:

- `debt_to_equity`
- `average_volume`
- later: beta, drawdown, borrow risk, earnings date, event risk

## Current Score

`ValuePoolFilter` produces:

- `approved`
- `reasons`
- `score`
- `score_breakdown`

Breakdown categories:

- `valuation`
- `quality`
- `demand`
- `safety`

The first weights are:

```text
valuation: 35%
quality:   30%
demand:    20%
safety:    15%
```

This is intentionally simple. It is meant to be understandable and testable
before becoming sophisticated.

## What Goes In First

For early paper testing, use highly liquid US stocks/ETFs:

- AAPL
- MSFT
- QQQ
- SPY

Then add more symbols only when:

- financial data can be populated
- volume is high enough
- spread is usually tight
- the company passes basic quality and valuation checks
- the system can explain why it entered the pool

## What Should Not Go In Yet

Avoid early automation on:

- low volume small caps
- meme names with unstable spreads
- companies with negative earnings and weak cash flow
- symbols near major unresolved events
- options and leveraged ETFs

## Learning Path

Add one concept at a time:

```text
PE -> forward PE -> FCF -> margins -> ROIC -> growth -> revisions -> event risk
```

Every new concept should become:

- one field
- one scoring rule
- one test
- one simulation output

That keeps the system explainable while the strategy grows.
