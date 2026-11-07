"""Lossless current-table candidate; original immutable archive is never edited."""
from contextlib import closing
import base64
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import struct


def quoted(name):return '"'+name.replace('"','""')+'"'


def row_hash(rows):
    digest=hashlib.sha256();count=0
    for row in rows:
        count+=1
        for value in row:
            if value is None:kind,data=b'N',b''
            elif isinstance(value,bytes):kind,data=b'B',value
            elif isinstance(value,str):kind,data=b'S',value.encode()
            elif isinstance(value,int):kind,data=b'I',str(value).encode()
            elif isinstance(value,float):kind,data=b'F',struct.pack('!d',value)
            else:raise ValueError('Unsupported SQLite value')
            digest.update(kind+len(data).to_bytes(8,'big')+data)
        digest.update(b'ROW_END')
    return count,digest.hexdigest()


def build(source,destination):
    source=Path(source).absolute();destination=Path(destination).absolute()
    if source.is_symlink() or destination.is_symlink() or not source.is_file() or destination.exists() or source.resolve()==destination.resolve():
        raise ValueError('Existing plain source and new distinct destination required')
    if Path(str(source)+'-wal').exists() and Path(str(source)+'-wal').stat().st_size:raise ValueError('Only a reconciled immutable snapshot without WAL accepted')
    with source.open('rb') as f:source_hash=hashlib.file_digest(f,'sha256').hexdigest()
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as src:
        src.execute('PRAGMA query_only=ON')
        if src.execute('PRAGMA quick_check').fetchall()!=[('ok',)]:raise ValueError('Source integrity failed')
        objects=src.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL ORDER BY rowid").fetchall()
        removed=[name for kind,name,table,sql in objects if kind=='table' and name.startswith('legacy_epoch_')]
        retained=[r for r in objects if not r[1].startswith('legacy_epoch_') and not r[2].startswith('legacy_epoch_')]
        for kind,name,table,sql in retained:
            if 'legacy_epoch_' in sql.lower() or 'CREATE VIRTUAL TABLE' in sql.upper():raise ValueError('Explicit schema dependency/virtual table review required: '+name)
        tables=[r for r in retained if r[0]=='table'];proof={}
        destination.parent.mkdir(parents=True,exist_ok=True)
        with destination.open('xb'):pass
        destination.chmod(0o600)
        with closing(sqlite3.connect(destination)) as dst:
            with dst:
                for kind,name,table,sql in tables:dst.execute(sql)
                for kind,name,table,sql in tables:
                    columns=[row[1] for row in src.execute('PRAGMA table_xinfo('+quoted(name)+')') if row[6]==0]
                    without='WITHOUT ROWID' in sql.upper()
                    alias=next((a for a in ('rowid','_rowid_','oid') if a not in columns),None)
                    if not without and alias is None:raise ValueError('Unaddressable rowid')
                    select=('SELECT * FROM '+quoted(name)+' ORDER BY '+','.join(quoted(row[1]) for row in sorted(src.execute('PRAGMA table_info('+quoted(name)+')'),key=lambda r:r[5]) if row[5])) if without else 'SELECT '+alias+',* FROM '+quoted(name)+' ORDER BY '+alias
                    insert_columns=columns if without else [alias,*columns]
                    values='SELECT '+','.join(quoted(c) for c in insert_columns)+' FROM '+quoted(name)+('' if without else ' ORDER BY '+alias)
                    cursor=src.execute(values)
                    while batch:=cursor.fetchmany(256):dst.executemany('INSERT INTO '+quoted(name)+'('+','.join(quoted(c) for c in insert_columns)+') VALUES('+','.join('?' for _ in insert_columns)+')',batch)
                    before=row_hash(src.execute(select));after=row_hash(dst.execute(select))
                    if before!=after:raise ValueError('Retained row/rowid digest differs: '+name)
                    proof[name]={'rows':before[0],'row_digest':before[1]}
                for kind,name,table,sql in retained:
                    if kind in ('index','view','trigger'):dst.execute(sql)
                if src.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone():
                    for name,seq in src.execute('SELECT name,seq FROM sqlite_sequence'):
                        if name in proof:
                            dst.execute('DELETE FROM sqlite_sequence WHERE name=?',(name,));dst.execute('INSERT INTO sqlite_sequence VALUES(?,?)',(name,seq))
            for pragma in ('user_version','application_id'):dst.execute('PRAGMA '+pragma+'='+str(src.execute('PRAGMA '+pragma).fetchone()[0]))
            if dst.execute('PRAGMA integrity_check').fetchall()!=[('ok',)] or dst.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('Candidate integrity/foreign keys failed')
            mode=src.execute('PRAGMA journal_mode').fetchone()[0]
            if mode in ('wal','delete'):dst.execute('PRAGMA journal_mode='+mode)
    with source.open('rb') as f:
        if hashlib.file_digest(f,'sha256').hexdigest()!=source_hash:raise ValueError('Source changed during build')
    return {'status':'VERIFIED_CANDIDATE_NOT_ACTIVATED','source':str(source),'source_sha256':source_hash,'source_bytes':source.stat().st_size,
            'destination':str(destination),'candidate_bytes':destination.stat().st_size,'retained':proof,'isolated_legacy_tables':removed,
            'source_deleted':False,'production_activated':False,'historical_replay_allowed':False,'grants_trading_permission':False}
