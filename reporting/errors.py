"""Offline error registry and lossless (except secrets) provider diagnostics."""
import errno
import re
import socket
import ssl
import json
from urllib.error import HTTPError
from datetime import datetime, timezone

# code: module, dependency, severity, retryable, reason, action
REGISTRY = {
 'SYS-LOCAL-001': ('system','local.machine','error','conditional','Local machine unavailable','Inspect OS health'),
 'NET-IFACE-001': ('connectivity','network.interface','error','conditional','Network interface unavailable','Restore interface'),
 'NET-ROUTE-001': ('connectivity','network.route','error','conditional','Route unavailable','Inspect routing and VPN'),
 'NET-DNS-001': ('connectivity','network.dns','error','conditional','DNS resolution failed','Restore resolver and rerun preflight'),
 'NET-ENDPOINT-001': ('connectivity','network.endpoint','error','conditional','Endpoint unreachable','Check service and route'),
 'NET-TLS-001': ('connectivity','network.tls','error','conditional','TLS validation failed','Check certificate and local clock; never disable TLS validation'),
 'IBKR-CONN-001': ('ibkr','ibkr.endpoint','error','conditional','IBKR connection unavailable','Reconnect through existing IBKR adapter'),
 'IBKR-SESSION-002': ('ibkr','ibkr.session','error','no','IBKR session not authenticated','Human authentication required'),
 'IBKR-CALLBACK-001': ('ibkr','ibkr.account_callback','error','conditional','Account callback not confirmed','Obtain account reconciliation evidence'),
 'DATA-MARKET-001': ('data','market.data','error','conditional','Market data unavailable','Restore existing data stream'),
 'DATA-STALE-001': ('validation','data.freshness','error','conditional','Data is stale','Wait for trusted fresh local persistence'),
 'DATA-CONFLICT-001': ('validation','data.consistency','error','no','Local and online data disagree','Reconcile provenance; do not overwrite silently'),
 'REPORT-DATA-INCOMPLETE': ('report','data.completeness','error','conditional','Report data incomplete','Reconcile required local data, never substitute zero'),
 'REPORT-GEN-001': ('report','local.renderer','error','conditional','Report generation failed','Inspect renderer diagnostics'),
 'REPORT-HASH-001': ('report','artifact.hash','error','no','Accepted artifact changed','Generate and explicitly approve a new artifact'),
 'REPORT-DATE-001': ('report','artifact.date','error','no','Report date is invalid for this dispatch','Archive old reports; explicit manual authorization required'),
 'REPORT-MOCK-001': ('report','artifact.provenance','error','no','Simulation cannot enter production delivery','Keep simulation artifacts in sandbox'),
 'DELIVERY-PAUSED-001': ('delivery','production.authority','info','no','Production delivery paused','Await explicit production acceptance and enable authorization'),
 'DELIVERY-UNKNOWN-001': ('delivery','remote.acknowledgement','error','no','Remote acceptance uncertain','NEVER AUTO RESEND; reconcile manually'),
 'FEISHU-AUTH-001': ('feishu','feishu.auth','error','no','Feishu authentication failed','Correct credentials through authorized operator'),
 'FEISHU-UPLOAD-001': ('feishu','feishu.upload','error','conditional','Image upload failed','Run full preflight before retry'),
 'FEISHU-SEND-001': ('feishu','feishu.send','error','conditional','Feishu explicitly rejected message','Inspect raw business response and retryability'),
 'LEDGER-DISK-001': ('ledger','local.disk','error','conditional','Local storage write failed','Restore writable storage before any network request'),
 'LEDGER-LOCK-001': ('ledger','local.ledger','info','conditional','Another process owns delivery lock','Read ledger after lock release'),
 'LEDGER-COMMIT-001': ('ledger','local.ledger','error','no','Acknowledgement commit or verification failed','Reconcile accepted remote result; never resend blindly'),
 'SCHED-AUTHORITY-001': ('trigger','trigger.ownership','error','no','Unrecognized or duplicate production authority','Inspect ownership history'),
 'RECOVERY-PREFLIGHT-001': ('recovery','dependency.health','error','conditional','Recovery prerequisites not verified','Recheck every required dependency'),
}

_SECRET = re.compile(r'(?i)^(?:(?:app|client|webhook)[_-]?secret|(?:access|refresh|tenant_access)[_-]?token|token|secret|authorization|password|credentials?|webhook[_-]?url|api[_-]?key|signature|bot[_-]?token|id[_-]?token|session[_-]?token|(?:ibkr[_-]?)?(?:passwd|password)|private[_-]?key|cookie)$')
def is_secret_field(name):
    return bool(_SECRET.search(str(name)))


def redact(value):
    if isinstance(value,dict):
        return {k:('[REDACTED]' if is_secret_field(k) else redact(v)) for k,v in value.items()}
    if isinstance(value,list):return [redact(v) for v in value]
    if isinstance(value,str):
        if value.lstrip().startswith(('{','[')):
            try:
                parsed=json.loads(value);clean=redact(parsed)
                if clean!=parsed:return json.dumps(clean,ensure_ascii=False)
            except ValueError:pass
        value=re.sub(r'(?<![0-9])[0-9]{5,}:[A-Za-z0-9_-]{25,}(?![A-Za-z0-9_-])','[REDACTED BOT TOKEN]',value)
        value=re.sub(r'\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{20,}|eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,})\b','[REDACTED AUTH TOKEN]',value)
        value=re.sub(r'https://[^\s\"\']+/bot/v2/hook/[^\s\"\']+', '[REDACTED WEBHOOK]',value)
        value=re.sub(r'(?i)Bearer\s+\S+','Bearer [REDACTED]',value)
        value=re.sub(r'(?i)((?:app[_ -]?secret|access[_ -]?token|api[_ -]?key|password|authorization|credential|token|secret)\s*[=:]\s*)[^,\s;]+',r'\1[REDACTED]',value)
    return value

def normalize(code, *, raw=None, now=None):
    module,dependency,severity,retryable,reason,action=REGISTRY[code]
    return dict(normalized_code=code,module=module,dependency=dependency,severity=severity,
                retryable=retryable,reason=reason,suggested_action=action,
                timestamp=(now or datetime.now(timezone.utc)).isoformat(),raw=redact(raw or {}))

def exception_error(exc, *, stage='', endpoint=None, now=None):
    if isinstance(exc,HTTPError):
        body=exc.read().decode('utf-8',errors='replace')
        try:response=json.loads(body)
        except ValueError:response={}
        code='FEISHU-AUTH-001' if exc.code in (401,403) else 'FEISHU-UPLOAD-001' if stage=='upload' else 'FEISHU-SEND-001'
        return normalize(code,now=now,raw={'exception_type':type(exc).__name__,'http_status':exc.code,'raw_code':response.get('code'),'raw_msg':response.get('msg'),'raw_response_body':body,'request_context':{'stage':stage,'endpoint':endpoint}})
    inner=getattr(exc,'reason',exc)
    code='FEISHU-UPLOAD-001' if stage=='upload' else 'SYS-LOCAL-001'
    if isinstance(inner,socket.gaierror):code='NET-DNS-001'
    elif isinstance(inner,ssl.SSLError):code='NET-TLS-001'
    elif isinstance(inner,(ConnectionError,TimeoutError)):code='NET-ENDPOINT-001'
    elif isinstance(inner,OSError):
        code='NET-ROUTE-001' if inner.errno in (errno.ENETUNREACH,errno.EHOSTUNREACH) else 'LEDGER-DISK-001'
    raw={'exception_type':type(exc).__name__,'errno':getattr(inner,'errno',None),'raw_message':str(exc),'affected_endpoint':endpoint,'stage':stage}
    return normalize(code,raw=raw,now=now)

def ibkr_error(request_id,errorCode,errorString,advancedOrderRejectJson=None,*,now=None):
    return normalize('IBKR-CONN-001',now=now,raw={'source':'IBKR','request_order_id':request_id,'raw_code':errorCode,'raw_message':errorString,'advancedOrderRejectJson':advancedOrderRejectJson})
