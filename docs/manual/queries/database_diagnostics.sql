-- Diagnostic queries used by the v0.1.0 Foundation Baseline manual.
-- Read-only only. Do not run UPDATE/INSERT/DELETE against trading_audit.sqlite3.

SELECT name
FROM sqlite_master
WHERE type = 'table'
ORDER BY name;

SELECT COUNT(*) AS recent_order_requests
FROM order_requests;

SELECT idempotency_key, created_at, mode, status
FROM order_requests
ORDER BY created_at DESC
LIMIT 10;

SELECT cycle_id, symbol, intent_type, execution_allowed, order_submitted, blocked_reason
FROM order_intent_events
ORDER BY rowid DESC
LIMIT 20;

SELECT symbol, current_layer, updated_at, has_active_order
FROM canonical_pool_state
ORDER BY updated_at DESC
LIMIT 20;

SELECT event_id, timestamp_utc, source_module, event_type, symbol, report_path
FROM event_store
ORDER BY rowid DESC
LIMIT 20;
