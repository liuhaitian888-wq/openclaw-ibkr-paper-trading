"""Persist current Paper facts as an opening baseline; never manufacture trades."""
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3

from trading.audit import AuditLog
from trading.order_ownership import classify_order, verified_historical_intents


def persist_readback(db, snapshot, expected_account, now, *, review_paths=()):
    observed = datetime.fromisoformat(snapshot['observed_at'])
    if (now.tzinfo is None or observed.tzinfo is None or not 0 <= (now-observed).total_seconds() <= 600
            or snapshot.get('source') != 'REAL_IBKR' or snapshot.get('complete') is not True
            or snapshot.get('environment') != 'PAPER' or not expected_account.startswith('DU')
            or snapshot.get('account_id') != expected_account
            or not {'summary','positions','orders','executions'} <= set(snapshot.get('end_markers', []))):
        raise ValueError('Fresh complete exact Paper readback required')
    positions, orders, executions = (snapshot[k] for k in ('positions','orders','executions'))
    if any(x.get('account') != expected_account for x in [*positions,*orders,*executions]):
        raise ValueError('Mixed account readback')
    if len({x['conId'] for x in positions}) != len(positions) or any(int(x['conId']) <= 0 for x in positions):
        raise ValueError('Ambiguous position identity')
    for p in positions:
        if not Decimal(p['position']).is_finite() or not Decimal(str(p['avgCost'])).is_finite():
            raise ValueError('Finite opening position required')
    if len({x['order_id'] for x in orders}) != len(orders):
        raise ValueError('Order IDs collide across clients; reconciliation required')
    for o in orders:
        if not o.get('perm_id') or not o.get('order_type') or not o.get('tif'):
            raise ValueError('Complete broker order fields required')
    for e in executions:
        if not e.get('exec_id') or e.get('price') is None:
            raise ValueError('Complete execution identity and price required')
    encoded = json.dumps(snapshot, sort_keys=True, ensure_ascii=False)
    identity = hashlib.sha256(encoded.encode()).hexdigest()
    path = Path(db)
    # A complete original DB backup precedes the first baseline publication.
    with closing(sqlite3.connect(path)) as c:
        initialized = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='paper_readback_baselines'").fetchone()
        if not initialized:
            backup = path.parent/'baseline-backups'
            backup.mkdir(mode=0o700,exist_ok=True)
            destination = backup/('before-'+identity+'.sqlite3')
            if destination.exists():
                raise ValueError('Existing backup needs explicit reconciliation')
            with closing(sqlite3.connect(destination)) as target:
                c.backup(target)
    with closing(sqlite3.connect(path)) as c, c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('CREATE TABLE IF NOT EXISTS paper_readback_baselines (account TEXT PRIMARY KEY, observed_at TEXT NOT NULL, snapshot_sha256 TEXT NOT NULL, payload_json TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS paper_readback_observations (snapshot_sha256 TEXT PRIMARY KEY, account TEXT NOT NULL, observed_at TEXT NOT NULL, payload_json TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS current_broker_positions (account TEXT NOT NULL, con_id INTEGER NOT NULL, observed_at TEXT NOT NULL, payload_json TEXT NOT NULL, PRIMARY KEY(account,con_id))')
        if c.execute('SELECT 1 FROM paper_readback_observations WHERE snapshot_sha256=?',(identity,)).fetchone():
            return dict(status='ALREADY_PERSISTED', snapshot_sha256=identity, grants_trading_permission=False)
        latest = c.execute('SELECT max(observed_at) FROM paper_readback_observations WHERE account=?',(expected_account,)).fetchone()[0]
        if latest and observed < datetime.fromisoformat(latest):
            raise ValueError('Out-of-order snapshot cannot replace current facts')
        c.execute('INSERT OR IGNORE INTO paper_readback_baselines VALUES (?,?,?,?)',(expected_account,observed.isoformat(),identity,encoded))
        c.execute('INSERT INTO paper_readback_observations VALUES (?,?,?,?)',(identity,expected_account,observed.isoformat(),encoded))
        c.execute('DELETE FROM current_broker_positions WHERE account=?',(expected_account,))
        for position in positions:
            payload = dict(position, source='REAL_IBKR_OPENING_OR_CURRENT', historical_cost_verified=False,
                           synthetic_execution_created=False)
            c.execute('INSERT INTO current_broker_positions VALUES (?,?,?,?)',(expected_account,position['conId'],observed.isoformat(),json.dumps(payload,sort_keys=True)))
        current_ids = {o['order_id'] for o in orders}
        prior_orders = c.execute('SELECT order_id,raw_json FROM broker_orders WHERE account=? AND completed=0',(expected_account,)).fetchall()
        absent = [i for i,raw in prior_orders if i not in current_ids and json.loads(raw).get('status') not in ('Filled','Cancelled','ApiCancelled','Inactive')]
        ownership = []
        for raw in orders:
            order = dict(raw, environment='PAPER')
            owner = classify_order(order, verified_historical_intents(order,review_paths,account=expected_account,environment='PAPER'),account=expected_account,environment='PAPER',external_evidence=order.get('client_id')==0 and not order.get('order_ref'))
            order['ownership'] = owner
            ownership.append(dict(perm_id=order['perm_id'],**owner))
            AuditLog._upsert_broker_order(c,order,observed.isoformat(),external=owner['ownership']!='SYSTEM_OWNED')
        for execution in executions:
            AuditLog._upsert_execution(c,dict(execution,environment='PAPER'),observed.isoformat())
        # Reflect activity for existing pool members without enrolling held stocks in a strategy.
        for symbol,payload in c.execute('SELECT symbol,payload_json FROM canonical_pool_state').fetchall():
            state = json.loads(payload)
            active = [o for o in orders if o['symbol']==symbol]
            uncertain = [i for i,raw in prior_orders if i in absent and json.loads(raw).get('symbol')==symbol]
            held = [p for p in positions if p['symbol']==symbol]
            state['broker_readback'] = dict(observed_at=observed.isoformat(),snapshot_sha256=identity,positions=held,orders=active,absent_prior_order_ids=uncertain,historical_complete=False)
            c.execute('UPDATE canonical_pool_state SET has_active_order=?,payload_json=? WHERE symbol=?',(int(bool(active or uncertain)),json.dumps(state,sort_keys=True),symbol))
        stored = [json.loads(row[0]) for row in c.execute('SELECT payload_json FROM current_broker_positions WHERE account=?',(expected_account,))]
        if {(p['conId'],p['position'],p['avgCost']) for p in stored} != {(p['conId'],p['position'],p['avgCost']) for p in positions}:
            raise ValueError('Position readback mismatch')
        result = dict(status='CURRENT_BASELINE_MATCHED' if not absent else 'MISSING_ORDER_OUTCOME_REQUIRES_RECONCILIATION',
                      snapshot_sha256=identity,observed_at=observed.isoformat(),account=expected_account,
                      positions=len(positions),active_orders=len(orders),executions_observed=len(executions),
                      absent_prior_order_ids=absent,ownership=ownership,historical_complete=False,
                      synthetic_executions_created=0,grants_trading_permission=False)
        stamp = now.astimezone(timezone.utc).isoformat()
        c.execute('INSERT INTO reconciliation_runs (started_at,completed_at,status,order_count,execution_count,external_active_count,messages_json) VALUES (?,?,?,?,?,?,?)',
                  (stamp,stamp,result['status'],len(orders),len(executions),sum(o['ownership']=='UNKNOWN' for o in ownership),json.dumps(result,sort_keys=True)))
        return result
