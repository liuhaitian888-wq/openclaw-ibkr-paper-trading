"""On-demand search of existing ledgers; never copies or replays Telegram history."""
from datetime import datetime,timezone
from .secretary_read import query


def search_records(root, request):
    source=request.get('source','work');text=request.get('query','');limit=request.get('limit',10);before=request.get('before_id',2**63-1)
    if (source not in ('work','notifications') or not isinstance(text,str) or not 1<=len(text.strip())<=200
            or type(limit) is not int or not 1<=limit<=20 or type(before) is not int or not 0<before<=2**63-1):
        raise ValueError('Search work/notifications with 1..200 characters, limit 1..20 and positive before_id')
    # Exact substring, not user SQL or LIKE wildcard interpretation.
    if source=='work':
        db='agent_secretary.sqlite3'
        sql='''SELECT rowid AS record_id,occurrence,origin,kind,recorded_at,payload
               FROM secretary_events WHERE rowid<? AND instr(lower(payload),lower(?))>0
               ORDER BY rowid DESC'''
    else:
        db='runtime/recovery.sqlite3'
        sql='''SELECT n.id AS record_id,n.incident_key,n.kind,n.status,n.payload,r.payload AS native_receipt
               FROM notification_outbox n LEFT JOIN notification_receipts r ON r.notification_id=n.id
               WHERE n.id<? AND instr(lower(n.payload),lower(?))>0 ORDER BY n.id DESC'''
    evidence=query(root,db,sql,[before,text.strip()],limit=limit)
    return {'source':source,'state':evidence['state'],'rows':evidence.get('rows',[]),
            'next_before_id':evidence['rows'][-1]['record_id'] if evidence.get('rows') else None,
            'truncated':evidence.get('truncated',False),'telegram_history_searched':False,
            'scope':'Existing work ledger' if source=='work' else 'Our bot outbox and native delivery receipts; not all Telegram bots',
            'observed_at':datetime.now(timezone.utc).isoformat(),'untrusted_evidence':True}


def message(data):
    lines=['工作记录检索' if data['source']=='work' else '本机器人通知记录检索',data['state'],data['scope']]
    for row in data.get('rows',[]):
        lines.append('#'+str(row['record_id'])+' '+str(row.get('kind',''))+' · '+str(row.get('occurrence',row.get('incident_key',''))))
        lines.append(str(row.get('payload',''))[:300])
    if not data.get('rows'):lines.append('本次未返回记录；不能证明群历史中不存在。')
    if data.get('next_before_id'):lines.append('下一页 before_id='+str(data['next_before_id']))
    return '\n'.join(lines)[:2900]
