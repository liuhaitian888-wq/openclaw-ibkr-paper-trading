"""Atomic protection recovery digest; individual evidence remains queryable."""
from contextlib import closing
import hashlib
import json


def ingest_recoveries(store, batch):
    """Publish one digest for newly closed incidents, never replay older sends.

    The producer supplies one complete broker observation. The transaction hides
    individual PENDING recoveries from the sender until they are suppressed and
    their digest is durable. STARTED/UNKNOWN and prior receipts are untouched.
    """
    now=store.clock()
    with closing(store.connect()) as c,c:
        c.execute('BEGIN IMMEDIATE')
        members=[]
        for event,key,payload,*_ in batch:
            prior=c.execute('SELECT generation,state FROM incidents WHERE incident_key=?',(key,)).fetchone()
            inserted=store._ingest(c,event,key,json.dumps(payload,sort_keys=True),True,now)
            if not inserted or not prior or prior[1]!='OPEN':continue
            row=c.execute("SELECT id FROM notification_outbox WHERE incident_key=? AND generation=? AND kind='RECOVERY' AND status='PENDING'",(key,prior[0])).fetchone()
            if not row:continue
            ident=row[0]
            if c.execute('SELECT 1 FROM notification_delivery WHERE notification_id=?',(ident,)).fetchone():
                raise ValueError('Recovery unexpectedly has a delivery attempt')
            c.execute("UPDATE notification_outbox SET status='SUPPRESSED' WHERE id=?",(ident,))
            members.append(dict(event_id=event,notification_id=ident,symbol=payload['symbol'],
                                protection_status=payload['protection_status']))
        if not members:return None
        opened=[k.split(':',2)[2] for k, in c.execute("SELECT incident_key FROM incidents WHERE state='OPEN' AND incident_key LIKE 'paper-safety:protection:%' ORDER BY incident_key")]
        protected=sorted({m['symbol'] for m in members if m['protection_status']=='PROTECTED'})
        flat=sorted({m['symbol'] for m in members if m['protection_status']=='NO_EXPOSURE'})
        other=sorted({m['symbol'] for m in members if m['protection_status'] not in ('PROTECTED','NO_EXPOSURE')})
        lines=[f'本轮保护核验：{len(members)} 项恢复，仍待核验/处理 {len(opened)} 项。']
        for label,symbols in [('保护覆盖已核验',protected),('无持仓、无挂单，旧故障关闭',flat),('不适用股票保护，现金风险另查',other),('仍有问题',opened)]:
            if symbols:lines.append(label+'：'+', '.join(symbols[:30])+(' 等' if len(symbols)>30 else ''))
        lines.append('仅保护状态更新；连接、行情及交易门禁独立，不代表恢复交易。')
        digest=hashlib.sha256(json.dumps(members,sort_keys=True).encode()).hexdigest()
        payload=dict(scope='PAPER_SAFETY',severity='GREEN',reason='\n'.join(lines),
                     recovery_digest_version=1,recovered_count=len(members),unresolved_count=len(opened),
                     queued_at=now,incident_resolved_at=now,recovery_members=members,
                     grants_trading_permission=False,action_taken='合并恢复通知；逐标的证据保留在原事件中。',
                     user_action='通过 /inbox risk 和 /event 编号查看仍有问题及原始证据。')
        cursor=c.execute("INSERT INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES (?,1,'RECOVERY',?,'PENDING')",
                         ('paper-safety:protection-recovery-batch:'+digest,json.dumps(payload,sort_keys=True)))
        return cursor.lastrowid
