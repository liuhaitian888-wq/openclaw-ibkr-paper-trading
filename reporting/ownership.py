"""Auditable trigger metadata. Never invokes launchctl, cron or cloud APIs."""
from copy import deepcopy
from datetime import datetime,timezone
from .ledger import Ledger

class Ownership:
    def __init__(self,directory):self.store=Ledger(directory)
    def record(self,trigger_id,action,actor,reason,*,changes=None,now=None):
        if action not in ('create','modify','enable','pause','retire','transfer'):raise ValueError('Unknown lifecycle action')
        if not actor or not reason:raise ValueError('Actor and reason required')
        now=now or datetime.now(timezone.utc)
        with self.store.locked():
            state=self.store.read();items=state.setdefault('triggers',{});changes=deepcopy(changes or {})
            old=items.get(trigger_id)
            if action=='create':
                if old:raise ValueError('Trigger already exists')
                for field in ('owner','purpose','entrypoint','scope'):
                    if not changes.get(field):raise ValueError('Missing ownership field '+field)
                current={**changes,'enabled':False,'current_authority':False,'created_at':now.isoformat(),'predecessor':None,'successor':None,'transfer_reason':None,'retirement_reason':None}
            else:
                if old is None:raise ValueError('Unknown trigger')
                current={**old,**changes}
            if action=='enable':
                if not changes.get('activation_evidence'):raise ValueError('Activation evidence required')
                if any(k!=trigger_id and v.get('enabled') and v.get('scope')==current['scope'] for k,v in items.items()):raise ValueError('Second production authority')
                current.update(enabled=True,current_authority=True)
            if action in ('pause','retire','transfer'):current.update(enabled=False,current_authority=False)
            if action=='retire':current['retirement_reason']=reason
            if action=='transfer':
                successor=changes.get('successor')
                if successor not in items or successor==trigger_id:raise ValueError('Successor must already exist and differ')
                if items[successor].get('enabled'):raise ValueError('Disable successor before transfer')
                current['transfer_reason']=reason
                items[successor].update(predecessor=trigger_id,transfer_reason=reason,modified_at=now.isoformat())
                # Transfer records succession, but never enables a real or recorded scheduler.
            if action=='modify' and any(k in changes for k in ('enabled','current_authority')):raise ValueError('Use explicit lifecycle action')
            current['modified_at']=now.isoformat();items[trigger_id]=current
            self.store.event(state,'TRIGGER_'+action.upper(),now,trigger_id=trigger_id,actor=actor,reason=reason,before=old,after=current)
            self.store.commit(state);return current
    def snapshot(self):return self.store.read().get('triggers',{})
