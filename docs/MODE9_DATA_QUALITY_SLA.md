# Mode 9 Universe Data-Quality SLA

Mode 9 is Paper-only. It may submit new Paper risk only when the API and TWS
are ready and this freshness gate returns `execution_allowed=true`.

| Priority | Definition | SLA | Gate behavior |
| --- | --- | --- | --- |
| Critical | Open positions or open orders | Every symbol must have fresh bid and ask | Any stale symbol enters `SAFE_MODE` |
| High | Monitor, hot, or trade pool | At least 90% fresh | Below SLA enters `SAFE_MODE` |
| Abnormal | Current abnormal mover | At least 80% fresh | Below SLA enters `SAFE_MODE` |
| Normal | Remaining Universe | At least 70% current coverage; no more than 30% stale; every symbol revisited within four cycles | A failed coverage or rotation window enters `SAFE_MODE` |

The gate records coverage, stale count, priority breakdown, and rotation state
inside each Mode 9 cycle report. It deliberately does not require every normal
symbol to be permanently subscribed: finite L1 capacity is handled by rotation.
`SAFE_MODE` blocks only new risk; monitoring, reconciliation, audit storage,
and protective workflows continue.

## Live Paper observation

On 2026-09-02 the real Paper runner subscribed all 71 configured Level-1
symbols. During an after-hours freshness sample only 7 symbols met the
eight-second bid/ask SLA; the gate returned `SAFE_MODE`, submitted zero
orders, and the canonical six-layer bridge completed successfully. This is an
observation of the configured 71-symbol Universe, not a claim about the
account's theoretical market-data-line limit. The separate L1 capacity probe
remains the source of that measurement.
