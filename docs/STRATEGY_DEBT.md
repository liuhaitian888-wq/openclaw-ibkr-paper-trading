# Strategy Debt

This file tracks temporary strategy constants and heuristics that are acceptable for paper trading, but should be replaced or tuned with backtest and live paper evidence before scaling.

| ID | File / Function | Current Temporary Value | Why It Is Temporary | Future Better Strategy | Evidence Needed Before Changing |
|---|---|---:|---|---|---|
| STOP-001 | `trading/position_protection.py` / `DEFAULT_STOP_PCT` | `0.05` | Fallback stop distance is used when ATR is unavailable. | Symbol/session/regime-aware fallback based on realized volatility and holding-period tests. | Backtests plus paper evidence comparing stop-out rate, drawdown, and recovery behavior. |
| STOP-002 | `trading/position_protection.py` / `MIN_STOP_PCT` | `0.03` | Minimum stop distance is a conservative floor, not calibrated by symbol liquidity or volatility buckets. | Dynamic minimum by ATR bucket, spread regime, and session. | Distribution of normal intraday adverse movement by symbol and session. |
| STOP-003 | `trading/position_protection.py` / `MAX_STOP_PCT` | `0.12` | Maximum stop distance caps risk without portfolio-level optimization. | Capital-at-risk cap tied to portfolio drawdown, position sizing, and volatility regime. | Portfolio simulations showing max drawdown and stop distance trade-offs. |
| STOP-004 | `trading/position_protection.py` / `ATR_MULTIPLIER` | `1.5` | ATR multiplier has not been validated by market regime or expected holding period. | Tune multiplier by symbol class, ATR regime, and paper-trading fill outcomes. | Backtest grid and paper logs for triggered stops, slippage, and false stop-outs. |
| STOP-005 | `trading/position_protection.py` / `SPREAD_MULTIPLIER` | `3.0` | Spread-based widening is a paper-trading heuristic for bad liquidity. | Session-aware spread model using median spread and order book quality. | Spread history, fill quality, and rejected/immediate-trigger repair cases. |
| STOP-006 | `trading/position_protection.py` / `STALE_QUOTE_MS` | `5000` | Quote freshness threshold is not tuned for premarket, regular hours, and afterhours separately. | Session-specific quote freshness policy. | Quote-age distribution and repair preview rejection analysis by session. |
| STOP-007 | `trading/position_protection.py` / `REPAIR_MAX_PER_CYCLE` | `10` | Repair throughput limit is not validated for many-position portfolios. | Portfolio-level repair scheduler with risk priority and order-rate awareness. | Paper runs with many positions, API pacing data, and duplicate-order audit logs. |
