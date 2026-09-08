"""Timer/network events request reevaluation, never grant Trading permissions."""
def recover(delivery,manifest,now,approved_hash):
    # Reuses the same hash, ledger, UNKNOWN, retry and preflight checks.
    return delivery.attempt(manifest,now,approved_hash=approved_hash,trigger='recovery')

def trading_recovery_plan(health):
    required=('ibkr.endpoint','ibkr.session','ibkr.account_callback','market.data','data.freshness')
    return {'observations':[health.health(k) for k in required],
            'actions':'Delegate reconnect/resync to existing Trading adapters; no gate mutation',
            'new_risk_authority':'existing Trading-specific safety gates',
            'grants_new_risk':False}
