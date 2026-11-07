"""Model-selected news research scope; never changes the execution universe."""
import json,os,tempfile,re
from .database_console import contained
from .intelligence import held_symbols


def effective_symbols(root,config,state):
    result=held_symbols(state) if state else list(config.get('baseline_position_symbols',[]));path=contained(root,'runtime/research-universe.json')
    choices=json.loads(path.read_text()).get('symbols',[]) if path.is_file() else config.get('watch_symbols',[])
    for symbol in choices:
        if isinstance(symbol,str) and re.fullmatch(r'[A-Z][A-Z0-9.-]{0,7}',symbol) and symbol not in result:result.append(symbol)
    return result[:12]


def select(archive,root,request,*,run,instruction,step):
    symbols=request.get('symbols');reasons=request.get('reasons')
    if (not isinstance(symbols,list) or not 1<=len(symbols)<=12 or len(set(symbols))!=len(symbols)
            or any(not isinstance(s,str) or not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,7}',s) for s in symbols)
            or not isinstance(reasons,dict) or set(reasons)!=set(symbols)
            or any(not isinstance(v,str) or not 1<=len(v)<=500 for v in reasons.values())):
        raise ValueError('One to twelve research symbols with explicit bounded reasons required')
    data={'symbols':symbols,'reasons':reasons,'source_run':run,'source_instruction':instruction,
          'execution_universe_changed':False,'positions_always_included_when_verified':True,'paid_subscriptions_changed':False}
    archive.append(run+':universe:'+str(step),'der-secretary',origin='MODEL',kind='RESEARCH_UNIVERSE_SELECTION',parent=instruction,payload=data)
    path=contained(root,'runtime/research-universe.json');path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.research-universe-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as f:json.dump(data,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)
    return {'state':'RESEARCH_SCOPE_APPLIED','selection':data,'scope':'News queries only; not strategy/trade permission; total request scope capped at 12 including held symbols'}
