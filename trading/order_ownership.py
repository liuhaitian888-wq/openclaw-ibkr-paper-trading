"""Broker exposure is always visible; ownership grants mutation authority separately."""

def classify_order(order, intents, *, account, environment, external_evidence=False):
    if not account or environment not in ('PAPER','LIVE') or order.get('account')!=account:
        return {'ownership':'UNKNOWN','reason':'Account/environment scope unverified','may_modify':False}
    matches=[i for i in intents if i.get('account')==account and i.get('environment')==environment
             and i.get('perm_id')==order.get('perm_id') and order.get('perm_id')]
    if len(matches)==1 and all(matches[0].get(k) for k in ('strategy','intent_id')) and (matches[0].get('run_id') or matches[0].get('source_id')):
        return {'ownership':'SYSTEM_OWNED','reason':'Scoped broker identity and intent lineage','may_modify':True,'intent':matches[0]['intent_id']}
    if matches:return {'ownership':'UNKNOWN','reason':'Incomplete/conflicting system lineage','may_modify':False}
    if external_evidence and not order.get('order_ref'):
        return {'ownership':'MANUAL_EXTERNAL','reason':'Scoped broker observation, no system claim, external-operation evidence','may_modify':False}
    return {'ownership':'UNKNOWN','reason':'Absence of intent alone is insufficient','may_modify':False}


def exposure_snapshot(orders,positions):
    # Never filter exposure by ownership; original account/contract fields survive.
    return {'orders':list(orders),'positions':list(positions),
            'symbols':sorted({str(x.get('symbol','')) for x in [*orders,*positions] if x.get('symbol')})}


def occurrence_scope(record, *, source_id, run_id=None, environment=None):
    """No synthetic account/run: legacy scope is explicitly separate from current."""
    account=record.get('account_id') or record.get('account')
    valid=bool(account and account not in ('DU123','x') and environment and run_id)
    return {'scope':'CURRENT_SCOPE' if valid else 'LEGACY_SCOPE','account':account,
            'environment':environment,'source':source_id,'run':run_id,
            'occurrence':record.get('event_id'),'observed_at':record.get('timestamp_utc')}
