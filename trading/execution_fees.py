"""Native fee facts with explicit revisions. Missing fees are never assumed to be zero."""
from decimal import Decimal
from datetime import datetime
from .instrument_facts import FIAT_CODES
import json


def initialize(connection):
    for statement in '''
    CREATE TABLE IF NOT EXISTS execution_fee_facts(
        exec_id TEXT PRIMARY KEY,currency TEXT NOT NULL,amount TEXT NOT NULL,
        account TEXT NOT NULL,revision INTEGER NOT NULL,received_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,source TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS execution_fee_account_time ON execution_fee_facts(account,updated_at);
    CREATE TABLE IF NOT EXISTS execution_fee_events(
        exec_id TEXT NOT NULL,revision INTEGER NOT NULL,payload TEXT NOT NULL,
        PRIMARY KEY(exec_id,revision));
    '''.split(';'):
        if statement.strip():connection.execute(statement)


def record(connection,exec_id,currency,amount,at,source):
    if not isinstance(exec_id,str) or not exec_id or len(exec_id)>200:raise ValueError('Native execution ID required')
    if not isinstance(currency,str) or currency not in FIAT_CODES:raise ValueError('Native fee currency required')
    if isinstance(amount,bool):raise ValueError('Boolean fee invalid')
    value=Decimal(str(amount))
    if not value.is_finite() or abs(value)>Decimal('1e100'):raise ValueError('Native fee is unavailable or unset')
    if source not in ('commissionReport','commissionAndFeesReport','commissionAndFeesReportProtoBuf'):raise ValueError('Native fee callback source required')
    if datetime.fromisoformat(at).tzinfo is None:raise ValueError('Aware native fee timestamp required')
    execution=connection.execute('SELECT account FROM executions WHERE exec_id=?',(exec_id,)).fetchone()
    account=str(execution[0]) if execution else ''
    if account and account!='DUQ503649':raise ValueError('Fee execution account mismatch')
    prior=connection.execute('SELECT currency,amount,account,revision,received_at FROM execution_fee_facts WHERE exec_id=?',(exec_id,)).fetchone()
    if prior and (prior[0],Decimal(prior[1]),prior[2])==(currency,value,account):return False
    revision=prior[3]+1 if prior else 1;received=prior[4] if prior else at
    payload={'exec_id':exec_id,'currency':currency,'amount':str(value),'account':account,'revision':revision,'received_at':received,'updated_at':at,'source':source}
    connection.execute('INSERT OR REPLACE INTO execution_fee_facts VALUES(?,?,?,?,?,?,?,?)',(exec_id,currency,str(value),account,revision,received,at,source))
    connection.execute('INSERT INTO execution_fee_events VALUES(?,?,?)',(exec_id,revision,json.dumps(payload,sort_keys=True)))
    return True


def bind_pending(connection,exec_id,at):
    # Account identity comes only from the canonical execution, never the fee report alone.
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='execution_fee_facts'").fetchone():return
    row=connection.execute("SELECT currency,amount,source FROM execution_fee_facts WHERE exec_id=? AND account=''",(exec_id,)).fetchone()
    if row:record(connection,exec_id,row[0],row[1],at,row[2])
