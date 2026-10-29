# L1/L2/L3 pause mechanism — existing T4-v2 and TradingService

User requirement: local faults stay local; actual strategy dependencies determine affected trades; only systemic unsafe conditions cause global new-order pause. No second controller or global Kill Switch mutation.

## Implementation ownership

- `trading/symbol_health.py::compute_pause_scopes`: pure projection of existing per-symbol health, completed K-lines, symbol order/risk checks and independently evidenced systemic safety. No environment-pair branching or broker transport.
- `trading/signal_scheduler.py`: existing StrategyBinding now accepts explicit `data_dependencies` per traded symbol. Default remains independent per-symbol for current single-symbol evaluators. A universe list alone does not mean all its targets share data. Unknown/invalid bindings remain locally blocked, not fabricated.
- `trading/paper_safety_monitor.py`: computes and persists scope decisions in existing paper_safety_state; records each pause/scope-clear/verified trade-resume transition in existing paper_callback_events with durable sequence, affected_symbols, affected_strategies, reason, scope and recovery_conditions. Resume requires fresh market, completed K-lines, account/order and risk; clearing a local symptom is not a business resume.
- `paper_safety_client.py`: reuses verified historicalDataEnd/completed updates as K-line evidence. No requirement to invent 5-second bars or subscribe from the acceptance timer. Unknown/future/stale/incomplete bars do not restore permission.
- `paper_safety_watch.py`: existing unique owner reads systemic safety periodically; monitoring/reconciliation/alerts/recovery continue in all pause levels. Existing operator PAUSED, maintenance, Kill Switch and transmit settings are read, never changed by pause logic. UNKNOWN order outcomes or stale/unverified global risk/state remain systemic blocks.
- `reporting/health.py` / `recovery.py`: central dependency resolver projects MARKET_DATA/PROTECTION/PAPER_SESSION for the requested trade only. Dependency invalidation preserves independently observed local module evidence, with its original freshness; missing/stale/intrinsic FAILED/OFFLINE/PAUSED safety is never promoted. Global market/protection aggregates remain diagnostic summaries, not automatic all-symbol execution authority.
- `production_guard.py` / `service.py`: service gate takes symbol/strategy; final broker guard resolves strategy from the canonical reserved intent and rejects mismatched symbol borrowing. Both enforce the same fresh dependency registry fingerprint and scoped decision. Other identity, ownership, manifest, unknown outcome, state, global risk, Kill Switch and audit-write checks remain mandatory. Error response includes structured pause metadata via workflow.py. Direct protection route uses its own guarded source and independent safety checks; no existing stop cancellation.

## Levels

| Level | Trigger | Effect |
|---|---|---|
| L1 SYMBOL_PAUSED | Invalid/stale/type mismatch/10197 or incomplete K-lines for one input; unverified target order/risk | Block affected new trade/risk addition; independent healthy targets remain eligible for their other existing gates |
| L2 STRATEGY_PAUSED / MULTI_SYMBOL_PAUSED | Actual declared shared data dependency or several local target failures | Block only dependent strategy-target rows. Even all watched feeds unavailable does not by itself create L3 |
| L3 GLOBAL_NEW_ORDERS_PAUSED | Identity/whole broker connection/control/global risk/authoritative state/reconciliation untrusted, operator hold, or inability to isolate risk | Block new orders; monitoring, broker readback, alerts and bounded data recovery continue |

Example declaration: dual_moving_average symbols[A,C], data_dependencies={A:[A,B],C:[C]}. If B fails, A under this strategy pauses; C and independent strategies on healthy A continue. Required input symbols outside the current watchlist remain explicitly unavailable; the policy does not silently subscribe to extra symbols.

## Verification and limits

Combined linked worktree complete suite722/58.305s PASS, real TCP disabled and temporary state. The earlier718-test run had one old mock-call-shape failure; context-free guard compatibility restored and cloud guard test now passes. Focused32/0.494s PASS; strengthened retained-stop fixture and rerun before commit. Cases: single/multiple/all failed feeds; shared inputs; independent peer keeps signal and real service/broker admission; identity/global failures; unknown/stale/config-changed context; local protection aggregate vs intrinsic failure; scope borrowing rejected; structured API rejection; no stop transport/cancel; historical K-lines without 5-second callbacks; no resume before risk; environment Live/Paper and Live/Live impact parity. No real fault injection or order submission.

The impact algorithm is environment-neutral. Existing broker adapters remain Paper-only; no Live execution is enabled or claimed. Signal-only evaluations may continue through an execution/operator hold if their data and portfolio inputs are valid; transmission is still false.

## Deployment boundary

Before this change cloud=1dc94d1 with safe monitor only. Freeze/test a monitor-only projection of the health/dependency/observer/watch/client changes; central resolver, TradingService/broker-guard/error changes stay candidate until full execution prerequisites pass. Report exact deployed Git identity separately. Do not describe monitoring metadata deployment as real order-path acceptance or claim a healthy-vs-failed real-market split when current broker data is unavailable.

Current existing operator/authority/risk gates already block trading. A runtime L3 caused by those facts must not be blamed on the number of10197 symbols. PFE order1/perm911411084 must be checked unchanged before/after takeover. Existing acceptance timer remains the only scheduled market acceptance reader.
