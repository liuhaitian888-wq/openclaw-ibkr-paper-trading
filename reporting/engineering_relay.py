"""Shared proposal mailbox. Model suggestions are evidence, never execution authority."""
from contextlib import closing
import hashlib
import json
from .secretary_queue import CONVERSATION


def proposals(archive):
    with closing(archive.connect()) as c:
        rows=c.execute("SELECT occurrence,payload FROM secretary_events WHERE kind='ENGINEERING_PROPOSAL' ORDER BY rowid DESC LIMIT 12").fetchall()
        results=[]
        for occurrence,payload in rows:
            status=c.execute("SELECT payload FROM secretary_events WHERE kind='ENGINEERING_STATUS' AND origin='SYSTEM' AND parent=? ORDER BY rowid DESC LIMIT 1",(occurrence,)).fetchone()
            results.append({'id':occurrence,'proposal':json.loads(payload),'engineering_status':json.loads(status[0]) if status else {'state':'PROPOSED_NOT_EXECUTED'}})
    return {'state':'SHARED_MAILBOX_READ','items':results,'automatic_deployment':False,'desktop_chat_wakeup_connected':False}


def propose(archive,request,*,instruction):
    fields=('title','observation','suggested_change');limits=(100,1500,1500)
    if any(not isinstance(request.get(k),str) or not 1<=len(request[k])<=limit for k,limit in zip(fields,limits)):raise ValueError('Bounded title, observation and suggested_change required')
    evidence=request.get('evidence')
    if not isinstance(evidence,list) or not 1<=len(evidence)<=5 or any(not isinstance(v,str) or not 1<=len(v)<=500 for v in evidence):raise ValueError('One to five explicit evidence references required')
    data={k:request[k] for k in fields};data['evidence']=evidence
    fingerprint=hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    key='engineering-proposal:'+fingerprint[:24]
    with closing(archive.connect()) as c:exists=c.execute('SELECT 1 FROM secretary_events WHERE occurrence=?',(key,)).fetchone()
    if not exists:archive.append(key,CONVERSATION,origin='MODEL',kind='ENGINEERING_PROPOSAL',parent=instruction,payload={**data,'grants_execution_permission':False})
    return {'state':'EXISTING_PROPOSAL' if exists else 'PROPOSAL_ARCHIVED','id':key,'automatic_deployment':False,'desktop_chat_wakeup_connected':False,'next':'Codex reads shared archive, verifies independently, and records ENGINEERING_STATUS; owner trading approvals remain independent'}
