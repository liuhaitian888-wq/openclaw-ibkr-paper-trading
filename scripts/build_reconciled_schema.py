"""Build an isolated schema candidate. Never publish or edit source databases."""
import ast
from contextlib import closing
import hashlib
import json
import re
from pathlib import Path
import sqlite3
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.reconcile_recovered_transition import digest


def stage_current_epoch(source, destination, *, account):
    """Preserve every legacy table in a new candidate; never publish production.

    Current execution tables start empty. The preserved historical namespace is
    intentionally unavailable to the normal order executor and its retry queue.
    """
    if account != 'DUQ503649':
        raise ValueError('Only the exact authorized Paper account is supported')
    source, destination = Path(source).absolute(), Path(destination).absolute()
    if source.is_symlink() or destination.is_symlink():
        raise ValueError('Symlink database paths are forbidden')
    if source.resolve() == destination.resolve() or destination.exists():
        raise ValueError('A new, distinct candidate destination is required')
    if not source.is_file():
        raise ValueError('Preserved source is missing')
    wal = Path(str(source) + '-wal')
    if wal.exists() and wal.stat().st_size:
        raise ValueError('Source WAL must be independently reconciled first')
    source_hash = digest(source)
    source_uri = source.resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(source_uri, uri=True)) as src:
        if src.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('Source integrity failure')
        if src.execute("SELECT 1 FROM sqlite_master WHERE type IN ('view','trigger') LIMIT 1").fetchone():
            raise ValueError('Views/triggers require explicit migration review')
        tables = [r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        if not tables or any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', t) or t.startswith('legacy_epoch_') for t in tables):
            raise ValueError('Unexpected or already isolated source schema')
        counts = {t: src.execute('SELECT count(*) FROM "' + t + '"').fetchone()[0] for t in tables}
        with destination.open('xb'):
            pass
        with closing(sqlite3.connect(destination)) as out:
            src.backup(out)
            with out:
                out.execute('BEGIN IMMEDIATE')
                indices = out.execute("SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL").fetchall()
                # Legacy rows stay intact. Explicit old indices can be omitted;
                # unique constraint autoindices follow their renamed tables.
                for (name,) in indices:
                    out.execute('DROP INDEX "' + name.replace('"', '""') + '"')
                for table in tables:
                    out.execute('ALTER TABLE "' + table + '" RENAME TO "legacy_epoch_' + table + '"')
    from trading.audit import AuditLog
    from trading.paper_audit_db import ensure_paper_automation_tables
    AuditLog(destination)
    ensure_paper_automation_tables(destination)
    with closing(sqlite3.connect(destination)) as out, out:
        for table, count in counts.items():
            actual = out.execute('SELECT count(*) FROM "legacy_epoch_' + table + '"').fetchone()[0]
            if actual != count:
                raise ValueError('Historical row count changed: ' + table)
        if out.execute('SELECT count(*) FROM order_requests').fetchone()[0]:
            raise ValueError('Current execution queue is not empty')
        if out.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or out.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Candidate integrity failure')
        if digest(source) != source_hash or (wal.exists() and wal.stat().st_size):
            raise ValueError('Source changed during staging')
        proof = dict(status='CURRENT_EPOCH_CANDIDATE_ONLY', account=account, environment='PAPER',
                     source=str(source), source_sha256=source_hash, legacy_counts=counts,
                     legacy_prefix='legacy_epoch_', current_order_requests=0,
                     historical_replay_allowed=False, grants_trading_permission=False,
                     omitted_legacy_indices=[r[0] for r in indices])
        out.execute('CREATE TABLE current_epoch_proof(payload TEXT NOT NULL)')
        out.execute('INSERT INTO current_epoch_proof VALUES (?)', (json.dumps(proof, sort_keys=True),))
    destination.chmod(0o600)
    return proof


def build(source, destination, code_root):
    source=Path(source).resolve(); destination=Path(destination).resolve()
    if source==destination:raise ValueError('Cannot overwrite source')
    source_hash=digest(source)
    if destination.exists():
        with closing(sqlite3.connect(destination.as_uri()+'?mode=ro',uri=True)) as c:
            proof=json.loads(c.execute('SELECT payload FROM schema_build_proof').fetchone()[0])
            if proof['source_sha256']!=source_hash:raise ValueError('Different source')
            if c.execute('pragma integrity_check').fetchall()!=[('ok',)]:raise ValueError('Integrity failure')
        return {'inserted':0,'status':'SCHEMA_CANDIDATE_ONLY'}
    definitions=[]
    for n in ast.walk(ast.parse((Path(code_root)/'trading/audit.py').read_text())):
        if isinstance(n,ast.Constant) and isinstance(n.value,str) and n.value.strip().startswith(('CREATE TABLE','CREATE INDEX')):definitions.append(n.value)
    with destination.open('xb'):pass
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(destination)) as out:
        src.backup(out)
        before=dict(out.execute("select name,0 from sqlite_master where type='table' and name not like 'sqlite_%'"))
        before={t:out.execute('select count(*) from "'+t+'"').fetchone()[0] for t in before}
        out.execute('BEGIN IMMEDIATE')
        try:
            for sql in definitions:
                if sql.strip().startswith('CREATE INDEX'):continue
                name=sql.strip().split()[5]
                cols=[x[1] for x in out.execute('pragma table_info("'+name+'")')]
                out.execute('ALTER TABLE "'+name+'" RENAME TO "schema_original_'+name+'"')
                out.execute(sql)
                fields=','.join('"'+x+'"' for x in cols)
                out.execute('INSERT INTO "'+name+'" ('+fields+') SELECT '+fields+' FROM "schema_original_'+name+'"')
                if out.execute('SELECT '+fields+' FROM "'+name+'" EXCEPT SELECT '+fields+' FROM "schema_original_'+name+'"').fetchone():raise ValueError('Projection changed')
            for sql in definitions:
                if sql.strip().startswith('CREATE INDEX'):out.execute(sql)
            cols=out.execute('pragma table_info(profit_sell_events)').fetchall()
            out.execute('ALTER TABLE profit_sell_events RENAME TO schema_original_profit_sell_events')
            out.execute('CREATE TABLE profit_sell_events ('+','.join('"'+x[1]+'" '+('INTEGER' if x[1]=='spread_ok' else x[2]) for x in cols)+')')
            rows=out.execute('select * from schema_original_profit_sell_events').fetchall();i=[x[1] for x in cols].index('spread_ok');converted=0
            for row in rows:
                row=list(row)
                if row[i]=='0':row[i]=0;converted+=1
                elif row[i] not in (None,0,1):raise ValueError('Unapproved spread representation')
                out.execute('INSERT INTO profit_sell_events VALUES ('+','.join('?' for _ in row)+')',row)
            for t,n in before.items():
                if out.execute('select count(*) from "'+t+'"').fetchone()[0]!=n:raise ValueError('Count mismatch '+t)
            proof={'source_sha256':source_hash,'source':str(source),'converted_spread_ok':converted,'counts':before,'status':'SCHEMA_CANDIDATE_ONLY','canonical_state':'UNAPPROVED'}
            out.execute('CREATE TABLE schema_build_proof (payload TEXT NOT NULL)');out.execute('insert into schema_build_proof values (?)',(json.dumps(proof,sort_keys=True),))
            if out.execute('pragma integrity_check').fetchall()!=[('ok',)]:raise ValueError('Integrity failure')
            if out.execute('pragma foreign_key_check').fetchall():raise ValueError('Foreign key violation')
            out.commit()
        except BaseException:out.rollback();raise
    if digest(source)!=source_hash:raise ValueError('Source changed')
    return {'inserted':converted,'status':'SCHEMA_CANDIDATE_ONLY'}

if __name__=='__main__':
    print(json.dumps(build(sys.argv[1],sys.argv[2],Path(__file__).resolve().parents[1])) )
