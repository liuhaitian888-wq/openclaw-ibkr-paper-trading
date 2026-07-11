# Risk By Session

Default policy shape:

- Overnight: lower order value, tighter spread, fewer open orders.
- Premarket: lower order value than regular, high-liquidity symbols preferred.
- Regular: largest paper order budget, normal quote freshness.
- Afterhours: lower order value, stricter quote freshness and stale order handling.

Global paper-only controls:

- Live trading disabled.
- Limit entry required.
- Protective stop required.
- Max open orders enforced.
- Max orders per session and per symbol enforced.
- Kill switch pauses the runtime.
