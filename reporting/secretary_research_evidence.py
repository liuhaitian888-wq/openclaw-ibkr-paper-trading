"""Fixed existing producer evidence; no collection, broker transport or writes."""
from datetime import datetime, timezone
import hashlib
import json
import time
from .database_console import contained
from .errors import redact

PATHS={'strategy_evidence':'reports/paper_strategy/latest.json','news_evidence':'runtime/news.latest.json'}


def freshness(value, now):
    try:
        at=datetime.fromisoformat(value.replace('Z','+00:00'))
        if at.tzinfo is None:raise ValueError('Timezone required')
        age=now-at.timestamp()
        if age<0:raise ValueError('Future evidence')
        return {'freshness':'FRESH' if age<=300 else 'STALE','age_seconds':round(age,3),'observed_at':value}
    except (TypeError,ValueError,AttributeError,OverflowError):
        return {'freshness':'UNKNOWN','observed_at':None}


def fields(row, names):
    return {k:row[k] for k in names if k in row}



CONFIG_FIELDS=('fast_window','slow_window','profit_target_pct','stop_loss_pct','min_gap_pct',
               'max_spread_pct','max_quote_age_ms','quantity','cooldown_steps')


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()).hexdigest()


def strategy_provenance(root):
    """Declared manifests only; never treats file contents as process approval."""
    result={}
    for rel,key in [('production.json','production'),('runtime/monitoring-deployment.json','monitoring')]:
        path=contained(root,rel)
        if not path.is_file():result[key]={'state':'NOT_CREATED','source_path':rel};continue
        with path.open('rb') as handle:raw=handle.read(64_001)
        if len(raw)>64_000:result[key]={'state':'EVIDENCE_TOO_LARGE','source_path':rel};continue
        try:
            data=json.loads(raw)
            if not isinstance(data,dict):raise ValueError('Manifest object required')
            item={'state':'DECLARED_MANIFEST','source_path':rel,'source_sha256':hashlib.sha256(raw).hexdigest(),
                  **fields(data,('commit','branch','environment','ready','mode','monitoring_approved','grants_trading_permission'))}
            if key=='production':
                cfg=data.get('strategy_configuration',{})
                if not isinstance(cfg,dict):raise ValueError('Invalid strategy configuration')
                parameters=fields(cfg,CONFIG_FIELDS)
                item.update(declared_parameters=parameters,declared_parameters_sha256=fingerprint(parameters),
                    strategy_configuration_approved=cfg.get('approved') is True,
                    signal_catalog_configuration_present=isinstance(data.get('signal_strategy_configurations'),dict) and bool(data['signal_strategy_configurations']))
            result[key]=item
        except (ValueError,TypeError,OverflowError):result[key]={'state':'INVALID_EVIDENCE','source_path':rel}
    result['scope']='Declared manifest identity, not proof of current process loading, readiness or trading permission'
    return result


def configuration_provenance(row, declared):
    cfg=row.get('strategy_configuration')
    if not isinstance(cfg,dict) or not cfg:return {'state':'REPORT_PARAMETERS_MISSING'}
    parameters=fields(cfg,CONFIG_FIELDS)
    result={'report_parameters_sha256':fingerprint(parameters),'parameter_source':'Existing per-symbol report, not inferred defaults'}
    current=declared.get('declared_parameters')
    if not parameters or not isinstance(current,dict) or not all(k in current for k in parameters):
        return {**result,'state':'COMPARISON_INCOMPLETE'}
    matches=all(current[k]==v for k,v in parameters.items())
    return {**result,'state':'MATCHING_DECLARED_PARAMETERS' if matches else 'PARAMETER_MISMATCH',
            'matches_current_declared_values':matches}


def read(root, request, *, now=None):
    name=request.get('name')
    if name not in PATHS or set(request)!={'name'}:raise ValueError('Fixed evidence tool; no custom paths or parameters')
    now=time.time() if now is None else now
    path=contained(root,PATHS[name])
    base={'source':'EXISTING_PRODUCER_SNAPSHOT','path':PATHS[name],
          'read_at':datetime.fromtimestamp(now,timezone.utc).isoformat(),
          'collection_triggered':False,'grants_trading_permission':False,'untrusted_evidence':True}
    if not path.is_file():return {**base,'state':'NOT_CREATED','freshness':'UNKNOWN'}
    with path.open('rb') as handle:raw=handle.read(512_001)
    if len(raw)>512_000:return {**base,'state':'EVIDENCE_TOO_LARGE','freshness':'UNKNOWN'}
    try:
        data=json.loads(raw)
        if not isinstance(data,dict):raise ValueError('Object required')
        if name=='strategy_evidence':
            symbols=data.get('symbols',{})
            if not isinstance(symbols,dict):raise ValueError('Symbol evidence required')
            declared=strategy_provenance(root)
            rows=[]
            for symbol,row in list(symbols.items())[:20]:
                if not isinstance(row,dict):raise ValueError('Invalid symbol evidence')
                rows.append({'symbol':symbol,**fields(row,('status','reason','strategy_configuration','signal',
                    'latest_completed_bar','history_bars','eligible_to_submit','transmit','execution_pause','remaining_gates')),
                    **freshness(row.get('observed_at'),now),
                    'configuration_provenance':configuration_provenance(row,declared.get('production',{}))})
            catalog=data.get('catalog') or {}
            if not isinstance(catalog,dict):raise ValueError('Invalid catalog')
            result={**base,'state':'PERSISTED_EVIDENCE','mode':data.get('mode'),'transmit':data.get('transmit'),
                    'symbols':rows,'truncated':len(symbols)>20,'declared_deployment':declared,
                    'catalog':fields(catalog,('mode','strategy_states','execution_enabled','execution_gates_unchanged')),
                    'catalog_freshness':'UNKNOWN','scope':'Per-symbol observation times only; scheduled names do not prove configured or deployed strategies'}
        else:
            providers=data.get('providers',[])
            if not isinstance(providers,list):raise ValueError('Provider list required')
            rows=[]
            body_budget=12000
            for provider in providers[:10]:
                if not isinstance(provider,dict):raise ValueError('Invalid provider')
                headlines=provider.get('headlines',[])
                if not isinstance(headlines,list):raise ValueError('Invalid headlines')
                articles=[]
                for headline in headlines[:10]:
                    if not isinstance(headline,dict):raise ValueError('Invalid headline')
                    item=fields(headline,('article_id','headline','time','retrieved_at','provider_code'))
                    # Only a retained, matching, content-verified body can be exposed.
                    body=provider.get('article_text')
                    matching_identity=(bool(provider.get('article_id')) and provider.get('code')==headline.get('provider_code')
                        and provider.get('article_provider_code')==provider.get('code')
                        and provider.get('article_id')==headline.get('article_id'))
                    content_ok=(isinstance(body,str) and bool(body.strip())
                        and hashlib.sha256(body.encode()).hexdigest()==provider.get('article_text_sha256')
                        and (provider.get('article_body_complete') is False or
                             provider.get('article_body_complete') is True and provider.get('article_text_sha256')==provider.get('article_sha256')))
                    body_fresh=freshness(provider.get('article_retrieved_at'),now)['freshness']=='FRESH'
                    trusted_source=data.get('source_kind')=='BROKER_API' and data.get('identity_verified') is True
                    matched=matching_identity and content_ok and body_fresh and trusted_source
                    item['body_available']=bool(matched)
                    item['body_freshness']=freshness(provider.get('article_retrieved_at'),now)
                    item.update(fields(provider,('article_content_key','article_body_state','article_body_complete',
                        'article_retrieved_at','article_published_at','article_expires_at','article_identity_key',
                        'article_revision_id','article_occurrence_key','article_revision_at','article_revision_time_state')))
                    if matched:
                        exposed=body[:min(2000,body_budget)]
                        body_budget-=len(exposed)
                        item['body_available']=bool(exposed)
                        item['body_budget_limited']=not exposed
                        if exposed:item.update(article_text=exposed,body_truncated=len(body)>len(exposed) or provider.get('article_body_complete') is False)
                    articles.append(item)
                rows.append({**fields(provider,('code','name','status','article_id','article_sha256','article_bytes')),
                             'articles':articles,'truncated':len(headlines)>10})
            result={**base,'state':'PERSISTED_EVIDENCE',**fields(data,('status','identity_verified','news_usable','symbol','started_at','completed_at')),
                    **freshness(data.get('completed_at'),now),'providers':rows,'truncated':len(providers)>10,
                    'scope':'Snapshot freshness is retrieval time, not article publication freshness; hashes alone are not readable bodies or complete feed coverage'}
        if name=='news_evidence':
            count=sum(bool(a.get('body_available')) for p in result['providers'] for a in p['articles'])
            result['readable_body_count']=count
            result['research_evidence_state']='BODY_EVIDENCE_AVAILABLE' if count else 'HEADLINES_ONLY_NO_BODY_RESEARCH'
        encoded=json.dumps(result,ensure_ascii=False,allow_nan=False)
        if len(encoded)>45_000:return {**base,'state':'EVIDENCE_PROJECTION_TOO_LARGE','freshness':'UNKNOWN','truncated':True}
        return redact(result)
    except (ValueError,TypeError,KeyError,OverflowError):
        return {**base,'state':'INVALID_EVIDENCE','freshness':'UNKNOWN'}
