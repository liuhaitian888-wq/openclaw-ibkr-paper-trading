"""Explicit dependency observations; unknown is never promoted to healthy by ping."""
from datetime import datetime,timezone
from .errors import normalize,exception_error

DEPENDENCIES = {
 'local.machine':('LOCAL_ONLY','SYS-LOCAL-001'),
 'network.interface':('LOCAL_ONLY','NET-IFACE-001'),
 'network.route':('NETWORK_REQUIRED','NET-ROUTE-001'),
 'network.dns':('NETWORK_REQUIRED','NET-DNS-001'),
 'ibkr.endpoint':('EXTERNAL_SERVICE_REQUIRED','IBKR-CONN-001'),
 'ibkr.session':('EXTERNAL_SERVICE_REQUIRED','IBKR-SESSION-002'),
 'ibkr.account_callback':('EXTERNAL_SERVICE_REQUIRED','IBKR-CALLBACK-001'),
 'market.data':('EXTERNAL_SERVICE_REQUIRED','DATA-MARKET-001'),
 'data.freshness':('LOCAL_ONLY','DATA-STALE-001'),
 'feishu.endpoint':('EXTERNAL_SERVICE_REQUIRED','NET-ENDPOINT-001'),
 'network.tls':('EXTERNAL_SERVICE_REQUIRED','NET-TLS-001'),
 'feishu.auth':('EXTERNAL_SERVICE_REQUIRED','FEISHU-AUTH-001'),
 'feishu.upload':('EXTERNAL_SERVICE_REQUIRED','FEISHU-UPLOAD-001'),
 'feishu.send':('EXTERNAL_SERVICE_REQUIRED','FEISHU-SEND-001'),
 'local.disk':('LOCAL_ONLY','LEDGER-DISK-001'),
 'local.ledger':('LOCAL_ONLY','LEDGER-COMMIT-001'),
}
DELIVERY_REQUIRED=('local.machine','network.interface','network.route','network.dns','network.tls','feishu.endpoint','feishu.auth','local.disk','local.ledger')

class Health:
    """Read-only probes are injected. No reconnect, orders or permissions here."""
    def __init__(self,probes=None):self.probes=probes or {};self.observations={}
    def health(self,dependency,now=None):
        now=now or datetime.now(timezone.utc)
        mode,code=DEPENDENCIES[dependency];probe=self.probes.get(dependency)
        result={'module':dependency,'dependency':dependency,'execution':mode,'state':'UNKNOWN','last_success':self.observations.get(dependency,{}).get('last_success'),'next_retry':None,'retry_allowed':'conditional','error_code':None,'observed_at':now.isoformat()}
        if probe:
            try:
                raw=probe()
                if isinstance(raw,dict) and raw.get('state')=='UNKNOWN':
                    result.update(state='UNKNOWN',evidence=raw)
                elif raw is True:result.update(state='HEALTHY',last_success=now.isoformat())
                else:result.update(state='BLOCKED',error_code=code,error=normalize(code,raw=raw if isinstance(raw,dict) else {'probe_result':raw},now=now))
            except Exception as exc:result.update(state='BLOCKED',error=exception_error(exc,endpoint=dependency,now=now));result['error_code']=result['error']['normalized_code']
        self.observations[dependency]=result
        return result
    def preflight(self,now=None):return [self.health(d,now) for d in DELIVERY_REQUIRED]
    def snapshot(self):return [self.health(d) for d in DEPENDENCIES]

# Shared module resolver. Existing delivery probes remain the leaf-observation API.
MODULE_DEPENDENCIES = {
 'NETWORK': (), 'DATABASE': (), 'LOCAL_STATE': ('DATABASE',),
 'AUDIT': ('DATABASE',), 'DIAGNOSTICS': (), 'REPORT_ARCHIVE': (),
 'IBKR_CONNECTION': ('NETWORK',), 'MARKET_DATA': ('IBKR_CONNECTION',),
 'NEWS': ('IBKR_CONNECTION',), 'ACCOUNT': ('IBKR_CONNECTION',), 'POSITIONS': ('ACCOUNT',),
 'ORDERS': ('ACCOUNT',), 'EXECUTIONS': ('ACCOUNT',),
 'CURRENCY_BOOK': ('ACCOUNT','EXECUTIONS','AUDIT'),
 'FINANCIAL_LEDGER': ('DATABASE',), 'EVENT_STORE': ('DATABASE',),
 'CANONICAL_STATE': ('DATABASE',),
 'RISK_CONTROLS': (),
 'RISK': ('ACCOUNT','POSITIONS','ORDERS'),
 'PROTECTION': ('ACCOUNT','POSITIONS','ORDERS','EXECUTIONS'),
 'PROTECTION_REPAIR': ('ACCOUNT','POSITIONS','ORDERS','EXECUTIONS','MARKET_DATA','AUDIT'),
 'CASH_CONVERSION': ('ACCOUNT','ORDERS','MARKET_DATA','AUDIT'),
 'PAPER_SESSION': ('PROTECTION','MARKET_DATA'),
 'STRATEGY': ('CANONICAL_STATE','MARKET_DATA','ACCOUNT','RISK','DATABASE','PROTECTION','PAPER_SESSION'),
 'ORDER_SUBMISSION': ('STRATEGY','ORDERS','EXECUTIONS','AUDIT'),
 'REPORT': ('DATABASE','CANONICAL_STATE','FINANCIAL_LEDGER'),
 'TELEGRAM': ('NETWORK',), 'SMTP': ('NETWORK',), 'FEISHU': ('NETWORK',), 'DELIVERY_LEDGER': (),
 'DELIVERY': ('REPORT','DELIVERY_LEDGER','FEISHU'),
 'INTELLIGENCE_PUBLIC': ('NETWORK',), 'INTELLIGENCE_BROKER': ('NEWS',),
 'SECRETARY_ARCHIVE': (),
 'MARKET_CLOCK': ('LOCAL_STATE',), 'ENGINEERING_WEEKLY': ('SECRETARY_ARCHIVE','LOCAL_STATE'),
 'BROAD_SCREENING': ('NETWORK','SECRETARY_ARCHIVE'), 'BROKER_SCANNER': ('IBKR_CONNECTION','SECRETARY_ARCHIVE'), 'SECRETARY_MODEL': ('NETWORK',),
 'SECRETARY_LIMITS': ('SECRETARY_ARCHIVE',),
 'SECRETARY': ('SECRETARY_ARCHIVE','SECRETARY_MODEL','TELEGRAM'),
 'GATEWAY_RECOVERY': ('LOCAL_STATE',),
 'WATCHDOG': ('LOCAL_STATE',), 'MANIFEST': ('LOCAL_STATE',),
}
MODULE_STATES = {'HEALTHY','DEGRADED','OFFLINE','WAITING_DEPENDENCY','RECOVERING','PAUSED','FAILED'}
LIVE_MODULES = {'CURRENCY_BOOK','MARKET_CLOCK','ENGINEERING_WEEKLY','CASH_CONVERSION','PROTECTION_REPAIR','SECRETARY_LIMITS','GATEWAY_RECOVERY','INTELLIGENCE_BROKER','INTELLIGENCE_PUBLIC','SECRETARY_MODEL','SECRETARY','SMTP','TELEGRAM','NEWS','NETWORK','IBKR_CONNECTION','MARKET_DATA','ACCOUNT','POSITIONS','ORDERS','EXECUTIONS','FEISHU','RISK','STRATEGY','ORDER_SUBMISSION','PROTECTION','PAPER_SESSION'}


def dependency_registry(observations):
    """Resolve the persisted primary route; changing route grants no permission."""
    registry=dict(MODULE_DEPENDENCIES)
    transport=observations.get('DELIVERY',{}).get('delivery_transport','feishu')
    provider={'telegram':'TELEGRAM','smtp':'SMTP','feishu':'FEISHU'}.get(transport)
    if provider is None:raise ValueError('Unknown primary delivery transport')
    if observations.get('RISK_CONTROLS',{}).get('enabled') is True:registry['RISK']=(*registry['RISK'],'RISK_CONTROLS')
    if observations.get('CURRENCY_BOOK',{}).get('enabled') is True:registry['ORDER_SUBMISSION']=(*registry['ORDER_SUBMISSION'],'CURRENCY_BOOK')
    registry['DELIVERY']=('REPORT','DELIVERY_LEDGER',provider)
    return registry


def resolve_modules(observations, *, now=None, max_age=120):
    """Pure, deterministic resolver. No network calls and no promotion by inference."""
    now=now or datetime.now(timezone.utc);result={}
    registry=dependency_registry(observations)
    primary=registry['DELIVERY'][-1]
    for name,deps in registry.items():
        raw=dict(observations.get(name,{}));state=raw.get('state','DEGRADED')
        if state not in MODULE_STATES:state='DEGRADED'
        freshness=raw.get('freshness','UNKNOWN')
        if freshness not in ('FRESH','STALE','UNKNOWN'):freshness='UNKNOWN'
        if name in LIVE_MODULES or name=='DIAGNOSTICS' or name in ('BROAD_SCREENING','BROKER_SCANNER'):
            try:age=(now-datetime.fromisoformat(raw['observed_at'])).total_seconds()
            except (KeyError,ValueError,TypeError):age=None
            limit = min(max_age,5) if name in ('PROTECTION','PAPER_SESSION') else max_age
            if name=='CURRENCY_BOOK':limit=10
            elif name in ('MARKET_CLOCK','ENGINEERING_WEEKLY'):limit=180
            elif name=='BROAD_SCREENING':limit=36*3600
            elif name=='BROKER_SCANNER':limit=3600
            if age is None or age<0 or age>limit:
                freshness='STALE' if raw else 'UNKNOWN'
                if state=='HEALTHY':state='DEGRADED'
        blocked=[d for d in deps if result[d]['state']!='HEALTHY' or (d in LIVE_MODULES and result[d]['freshness']!='FRESH')]
        reason=raw.get('reason','No verified observation')
        if blocked and state not in ('PAUSED','FAILED','OFFLINE'):
            state='WAITING_DEPENDENCY';reason='Dependency unavailable: '+', '.join(blocked)
            if name in LIVE_MODULES:freshness='STALE'
        if state=='HEALTHY' and name in LIVE_MODULES and freshness!='FRESH':
            state='DEGRADED';reason='Fresh data not established'
        result[name]={**raw,'active':(name not in ('CURRENCY_BOOK','MARKET_CLOCK','ENGINEERING_WEEKLY','PROTECTION_REPAIR','CASH_CONVERSION','BROAD_SCREENING','BROKER_SCANNER') or raw.get('enabled') is True) and (not name.startswith('INTELLIGENCE_') or raw.get('enabled') is True) and (name not in ('TELEGRAM','SMTP','FEISHU') or name==primary) and (name!='RISK_CONTROLS' or observations.get('RISK_CONTROLS',{}).get('enabled') is True) and (not name.startswith('SECRETARY') or observations.get('SECRETARY',{}).get('enabled') is True) and (name!='GATEWAY_RECOVERY' or raw.get('enabled') is True),'state':state,'freshness':freshness,'reason':reason,
            'blocking_dependency':blocked,'last_success':raw.get('last_success'),
            'last_failure':raw.get('last_failure'),'next_retry':raw.get('next_retry'),
            'recovery_state':raw.get('recovery_state','IDLE'),'observed_at':raw.get('observed_at')}
    result['SYSTEM']={'state':'HEALTHY' if all(x['state']=='HEALTHY' for x in result.values() if x['active']) else 'DEGRADED',
        'freshness':'UNKNOWN','reason':'Aggregated module view; not permission to trade',
        'blocking_dependency':[k for k,v in result.items() if v['active'] and v['state']!='HEALTHY'],
        'last_success':None,'last_failure':None,'next_retry':None,'observed_at':now.isoformat(),'recovery_state':'AGGREGATED'}
    return result


def safety_gate(action, modules, facts):
    """One side-effect policy. No caller can infer authority from socket success."""
    required={'ORDER_SUBMISSION_ALLOWED':('ORDER_SUBMISSION','MANIFEST'),
              'FEISHU_SEND_ALLOWED':('DELIVERY','MANIFEST'),
              'PRODUCTION_START_ALLOWED':('DATABASE','LOCAL_STATE','MANIFEST')}
    if action not in required:return {'allowed':False,'reasons':['Unknown action']}
    reasons=[]
    for name in required[action]:
        m=modules.get(name,{})
        if m.get('state')!='HEALTHY':reasons.append(name+' not HEALTHY')
        if name in LIVE_MODULES and m.get('freshness')!='FRESH':reasons.append(name+' not FRESH')
    if facts.get('maintenance',True):reasons.append('MAINTENANCE')
    if facts.get('manifest_approved') is not True:reasons.append('Manifest unapproved')
    if action!='PRODUCTION_START_ALLOWED':
        if facts.get('duplicate_or_unknown',True):reasons.append('Duplicate/uncertain operation')
        if facts.get('reconciled') is not True:reasons.append('Reconciliation incomplete')
    if action=='ORDER_SUBMISSION_ALLOWED':
        for k in ('identity_verified','ownership_verified','risk_allowed'):
            if facts.get(k) is not True:reasons.append(k)
        if facts.get('trading_paused',True):reasons.append('Trading PAUSED')
    if action=='FEISHU_SEND_ALLOWED' and facts.get('delivery_paused',True):reasons.append('Delivery PAUSED')
    return {'allowed':not reasons,'reasons':reasons}

# Bridge existing dependency probes to the shared graph (no duplicate ping loop).
PROBE_MODULES={'network.route':'NETWORK','ibkr.session':'IBKR_CONNECTION',
    'ibkr.account_callback':'ACCOUNT','market.data':'MARKET_DATA','local.disk':'DATABASE',
    'local.ledger':'DELIVERY_LEDGER','feishu.endpoint':'FEISHU'}

def module_view(health, *, now=None):
    now=now or datetime.now(timezone.utc);observations={}
    for dep,module in PROBE_MODULES.items():
        row=health.observations.get(dep,{})
        observations[module]={**row,'state':row.get('state') if row.get('state') in MODULE_STATES else 'DEGRADED',
            'freshness':'FRESH' if row.get('state')=='HEALTHY' else 'UNKNOWN',
            'reason':row.get('error_code') or 'Existing dependency probe'}
    return resolve_modules(observations,now=now)
