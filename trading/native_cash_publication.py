"""Atomic cash facts for the existing Paper monitor; no financial transport."""
from contextlib import closing
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
from .entry_admission import aware_stamp
from .native_cash_collector import CashbookFrameRejected
from .paper_safety_monitor import ACCOUNT


def publish_native_cashbook(root,monitor,book):
    root=Path(root).resolve();target=root/'runtime/currency-book.latest.json'
    if monitor.audit._path.parent.resolve()!=root or target.is_symlink() or target.parent.is_symlink():
        raise PermissionError('Canonical owned cashbook path required')
    with monitor.lock:
        now=monitor.clock();start=aware_stamp(book['cash_read_started_at']);end=aware_stamp(book['cash_read_finished_at'])
        receipt=book['settlement_receipt']
        if (book.get('source')!='BROKER_API' or book.get('account')!=ACCOUNT or book.get('grants_trading_permission') is not False
            or not monitor._complete() or book.get('connection_generation')!=monitor.state.get('api_protocol',{}).get('connection')
            or not 0<=now-end<=10 or not start<=end<=aware_stamp(book['observed_at'])<=now
            or start<monitor.state.get('latest_cash_change_at',0) or start<monitor.state.get('reconciled_at',0)
            or aware_stamp(receipt['started_at'])!=start or aware_stamp(receipt['finished_at'])!=end):
            raise CashbookFrameRejected('Current exact native cash generation and ordered snapshot required')
        with closing(monitor.audit._connect()) as c:
            c.execute('BEGIN')
            for sql in ("SELECT max(first_seen_at) FROM executions WHERE account='DUQ503649'",
                        "SELECT max(updated_at) FROM execution_fee_facts WHERE account='DUQ503649'"):
                latest=c.execute(sql).fetchone()[0]
                if latest and aware_stamp(latest)>start:raise CashbookFrameRejected('Cash read predates canonical execution or fee update')
        book=dict(book,broker_epoch=monitor.state['epoch'],broker_reconciled_at=monitor.state['reconciled_at'])
        payload=json.dumps(book,ensure_ascii=False,sort_keys=True,allow_nan=False)
        if len(payload.encode())>100000:raise ValueError('Bounded native cashbook required')
        if target.exists():
            if target.stat().st_size>100000:raise ValueError('Existing cashbook exceeds bounded evidence size')
            prior=json.loads(target.read_text())
            if prior.get('source')=='BROKER_API' and prior.get('account')==ACCOUNT and aware_stamp(prior['observed_at'])>end:
                raise CashbookFrameRejected('A later cash observation already exists; no stale overwrite')
        target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        # A failed partial is private and retained for diagnosis; never truncate latest.
        with tempfile.NamedTemporaryFile(mode='w',dir=target.parent,prefix='.cashbook-',suffix='.tmp',delete=False) as f:
            temporary=Path(f.name);f.write(payload);f.flush();os.fsync(f.fileno())
        temporary.replace(target)
        directory=os.open(target.parent,os.O_RDONLY)
        try:os.fsync(directory)
        finally:os.close(directory)
        monitor.state['currency_book_status']={'observed_at':book['observed_at'],'request_id':receipt['request_id'],
            'connection_generation':book['connection_generation'],'sha256':hashlib.sha256(payload.encode()).hexdigest(),
            'grants_trading_permission':False}
