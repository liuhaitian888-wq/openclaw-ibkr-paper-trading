"""Immutable prewire identity intent, not broker ownership or wire authority.

The caller owns/closes the SQLite connection and explicitly installs this
additive schema after migration validation. This module never opens a broker.
"""
import hashlib
import json
import sqlite3
from .entry_admission import decimal, aware_stamp

ACCOUNT = 'DUQ503649'
MAX_ID = 2147483647


def initialize_schema(connection):
    if not connection.in_transaction:
        raise PermissionError('Caller-owned transaction required for additive native schema')
    connection.execute('''CREATE TABLE IF NOT EXISTS native_order_preparations(
        identity TEXT PRIMARY KEY, prepared_at TEXT NOT NULL,
        fingerprint TEXT NOT NULL, proof_json TEXT NOT NULL)''')
    connection.execute('''CREATE TABLE IF NOT EXISTS native_prepared_order_ids(
        account TEXT NOT NULL, client_id INTEGER NOT NULL, order_id INTEGER NOT NULL,
        identity TEXT NOT NULL, leg TEXT NOT NULL,
        PRIMARY KEY(account,client_id,order_id), UNIQUE(identity,leg))''')


def positive_id(value):
    return type(value) is int and 0 < value <= MAX_ID


def bounded_identity(value):
    return isinstance(value, str) and 0 < len(value) <= 200 and not any(c in value for c in '\r\n\x00')


def get_preparation(connection, identity):
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_order_preparations'").fetchone():
        return None
    row=connection.execute('SELECT proof_json,fingerprint FROM native_order_preparations WHERE identity=?',(identity,)).fetchone()
    if not row:return None
    payload=json.loads(row[0])
    if (hashlib.sha256(row[0].encode()).hexdigest()!=row[1] or payload.get('identity')!=identity
            or payload.get('schema_version')!=1 or payload.get('source')!='NATIVE_PREWIRE_IDENTITY'
            or any(payload.get(k) is not False for k in ('broker_acknowledged','wire_prices_verified','partial_fill_coverage_verified','mutation_authorized','grants_trading_permission'))
            or payload.get('requires_final_wire_admission') is not True):
        raise ValueError('Native preparation fingerprint or non-authority boundary differs')
    rows=[tuple(r) for r in connection.execute('SELECT account,client_id,order_id,leg FROM native_prepared_order_ids WHERE identity=? ORDER BY leg',(identity,))]
    expected=[(payload['account'],payload['client_id'],payload['parent_order_id'],'PARENT'),
              (payload['account'],payload['client_id'],payload['stop_order_id'],'PROTECTION')]
    if rows!=expected:raise ValueError('Native identity reservation set differs; no automatic repair')
    return payload


def record_preparation(connection, identity, evidence, prepared_at):
    if not bounded_identity(identity):raise PermissionError('Exact bounded intent identity required')
    if not connection.in_transaction:
        raise PermissionError('Caller-owned transaction required for native preparation')
    at=aware_stamp(prepared_at)
    row=connection.execute('SELECT mode,status,proposal_json FROM order_requests WHERE idempotency_key=?',(identity,)).fetchone()
    if not row or row[0]!='PAPER_TRANSMIT' or row[1]!='RESERVED':
        raise PermissionError('Exact reserved Paper entry intent required')
    if connection.execute("SELECT 1 FROM order_events WHERE idempotency_key=? AND event_type='TRANSPORT_STARTED' LIMIT 1",(identity,)).fetchone():
        raise PermissionError('Started occurrence cannot be prepared again or replayed')
    proposal=json.loads(row[2])
    if (proposal.get('side')!='BUY' or type(proposal.get('quantity')) is not int or proposal['quantity']<=0
            or not 0<decimal(proposal.get('stop_price'))<decimal(proposal.get('limit_price'))):
        raise PermissionError('Long stock entry with an explicit lower stop required')
    claim=connection.execute('SELECT account,state,reserved_usd,fee_usd,broker_epoch,created_at FROM entry_cash_claims WHERE identity=?',(identity,)).fetchone()
    if (not claim or claim[0]!=ACCOUNT or claim[1]!='RESERVED' or not bounded_identity(claim[4])
            or aware_stamp(claim[5])>at or decimal(claim[3])<0
            or decimal(claim[2])<decimal(proposal['quantity'])*decimal(proposal['limit_price'])+decimal(claim[3])):
        raise PermissionError('Exact funded intent claim required; preparation releases no cash')
    generation=evidence.get('connection_generation');client=evidence.get('client_id')
    contract=evidence.get('contract',{});next_id=evidence.get('next_valid_id',{})
    parent=evidence.get('parent_order_id');stop=evidence.get('stop_order_id')
    if (evidence.get('source')!='NATIVE_PREWIRE_IDENTITY' or evidence.get('environment')!='PAPER'
            or evidence.get('account')!=ACCOUNT or evidence.get('broker_epoch')!=claim[4]
            or not bounded_identity(generation) or not positive_id(client)
            or contract.get('source')!='NATIVE_CONTRACT_DETAILS' or contract.get('complete') is not True
            or contract.get('connection_generation')!=generation or not positive_id(contract.get('request_id'))
            or contract.get('symbol')!=proposal['symbol'] or contract.get('sec_type')!='STK'
            or contract.get('currency')!='USD' or not positive_id(contract.get('con_id'))
            or not bounded_identity(contract.get('primary_exchange'))
            or not 0<decimal(contract.get('min_tick'))<=decimal('1e100')
            or not 0<=at-aware_stamp(contract['observed_at'])<=10
            or next_id.get('source')!='NATIVE_NEXT_VALID_ID' or next_id.get('connection_generation')!=generation
            or type(next_id.get('value')) is not int or not 0<=next_id['value']<=MAX_ID
            or not 0<=at-aware_stamp(next_id['observed_at'])<=10
            or not positive_id(parent) or not positive_id(stop) or stop!=parent+1
            or parent<max(1,next_id['value'])):
        raise PermissionError('Exact fresh native contract, connection and nonzero linked IDs required')
    # Only typed fields enter the immutable journal, not SDK objects or free prose.
    fixed_contract={k:contract[k] for k in ('source','complete','connection_generation','request_id',
        'symbol','sec_type','currency','con_id','primary_exchange','observed_at')}
    fixed_contract['min_tick']=str(decimal(contract['min_tick']))
    payload=dict(schema_version=1,identity=identity,account=ACCOUNT,environment='PAPER',client_id=client,
        connection_generation=generation,broker_epoch=claim[4],contract=fixed_contract,
        next_valid_id={k:next_id[k] for k in ('source','connection_generation','value','observed_at')},
        parent_order_id=parent,stop_order_id=stop,
        raw_proposal={k:proposal[k] for k in ('symbol','side','quantity','limit_price','stop_price')},
        source='NATIVE_PREWIRE_IDENTITY',broker_acknowledged=False,wire_prices_verified=False,
        partial_fill_coverage_verified=False,mutation_authorized=False,grants_trading_permission=False,
        requires_final_wire_admission=True)
    encoded=json.dumps(payload,sort_keys=True,allow_nan=False)
    if len(encoded.encode())>20000:raise ValueError('Bounded native identity preparation required')
    fingerprint=hashlib.sha256(encoded.encode()).hexdigest()
    prior=connection.execute('SELECT fingerprint FROM native_order_preparations WHERE identity=?',(identity,)).fetchone()
    if prior:
        if prior[0]!=fingerprint:raise PermissionError('Native identity preparation is immutable')
        get_preparation(connection,identity)
        return payload
    connection.execute('SAVEPOINT native_identity_preparation')
    try:
        connection.execute('INSERT INTO native_order_preparations VALUES(?,?,?,?)',(identity,prepared_at,fingerprint,encoded))
        for leg,order_id in (('PARENT',parent),('PROTECTION',stop)):
            connection.execute('INSERT INTO native_prepared_order_ids VALUES(?,?,?,?,?)',(ACCOUNT,client,order_id,identity,leg))
        connection.execute('''INSERT INTO order_events(idempotency_key,occurred_at,event_type,status,details)
            VALUES(?,?,'NATIVE_IDENTITY_PREPARED','RESERVED',?)''',(identity,prepared_at,json.dumps({'fingerprint':fingerprint,'grants_trading_permission':False})))
    except Exception as exc:
        connection.execute('ROLLBACK TO native_identity_preparation')
        connection.execute('RELEASE native_identity_preparation')
        if isinstance(exc,sqlite3.IntegrityError):raise PermissionError('Native order identity already reserved by another intent') from exc
        raise
    connection.execute('RELEASE native_identity_preparation')
    return payload
