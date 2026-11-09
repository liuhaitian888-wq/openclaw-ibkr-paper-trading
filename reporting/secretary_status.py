"""Read-only Telegram views of existing production evidence; no probes or recovery."""
from contextlib import closing
from datetime import datetime, timezone
import json
import sqlite3
from .health import resolve_modules
from .errors import redact

GROUPS = {
    'api': ('API与真实连接链路', ('SECRETARY_MODEL', 'SECRETARY_API_CREDENTIAL', 'IBKR_CONNECTION', 'ACCOUNT')),
    'cloud': ('云端运行状态', ('NETWORK', 'DIAGNOSTICS', 'SECRETARY_ARCHIVE', 'SECRETARY', 'TELEGRAM')),
    'market': ('行情运行状态', ('IBKR_CONNECTION', 'MARKET_DATA', 'MARKET_CLOCK', 'BROAD_SCREENING', 'BROKER_SCANNER')),
}


def read_json(path):
    if path.stat().st_size > 1000000:
        raise ValueError('Bounded status evidence required')
    return json.loads(path.read_text())


def display(root, group, *, now=None):
    now = now or datetime.now(timezone.utc)
    title, names = GROUPS[group]
    lines = [title, '查询时间：' + now.isoformat(), '来源：当前云端已有运行证据；不新建连接。']
    try:
        with closing(sqlite3.connect((root/'runtime/recovery.sqlite3').as_uri()+'?mode=ro', uri=True, timeout=.1)) as c:
            observations = {k: json.loads(v) for k, v in c.execute('SELECT name,payload FROM module_observations')}
        modules = resolve_modules(observations, now=now)
        for name in names:
            item = modules[name]
            # All menu evidence expires, including modules outside LIVE_MODULES.
            try:
                age = (now-datetime.fromisoformat(item['observed_at'])).total_seconds()
                current = 0 <= age <= (36*3600 if name=='BROAD_SCREENING' else 300)
            except (TypeError, ValueError, KeyError):
                current = False
            fresh = item['freshness'] if current else 'STALE/UNKNOWN'
            state = item['state'] if current else '未证实当前正常'
            lines.append(name+'：'+state+' / '+fresh+'\n观测：'+str(item.get('observed_at') or '无')+'\n原因：'+str(redact(item.get('reason', '无')) )[:220])
        if group == 'api':
            model = observations.get('SECRETARY_MODEL', {})
            lines.append('最近模型证据：provider='+str(model.get('provider', 'UNKNOWN'))+'，model='+str(model.get('model', 'UNKNOWN')))
            try:
                policy = read_json(root/'runtime/secretary-policy.json')
                lines.append('配置模型owner：'+str(policy.get('model_owner') or '未明确声明')+'；配置不等于连接成功。')
            except (OSError, ValueError, TypeError):
                lines.append('模型owner配置：UNKNOWN')
        if group == 'cloud':
            try:
                host = read_json(root/'runtime/cloud-status.json')
                lines.append('主机观测：'+str(host.get('observed_at', 'UNKNOWN')))
                lines.append('已有服务历史采样（非现场检查）：'+', '.join(str(k)+':'+str(v) for k,v in host.get('services', {}).items())[:600])
                lines.append('主机记录可能过期；收到本回复仅证明本次Telegram控制链路可达。')
            except (OSError, ValueError, TypeError):
                lines.append('主机采样：UNKNOWN，缺少可用记录。')
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
        lines.append('UNKNOWN：无法读取完整状态证据；不能认定正常。')
    if group == 'market':
        lines.append('休市、延迟行情与权限拒绝分别判断；订阅声明见 /marketdata，报价抽查见 /market_check。')
    lines.append('状态正常不代表允许交易；暂停与维护门禁独立。')
    return '\n'.join(lines)[:3800]
