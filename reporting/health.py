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
