"""Bounded private weekly evidence packet, no model spend or trading authority."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from zoneinfo import ZoneInfo

ZONE = ZoneInfo('Europe/Berlin')


def packet(archive, now, *, persist=False):
    if now.tzinfo is None:
        raise ValueError('Timezone-aware timestamp required')
    local = now.astimezone(ZONE)
    year, week, _ = local.isocalendar()
    key = f'engineering-weekly:{year}-W{week:02d}'
    with closing(archive.connect()) as c:
        existing = c.execute("SELECT payload FROM secretary_events WHERE occurrence=? AND kind='ENGINEERING_WEEKLY'", (key,)).fetchone()
        if existing:
            return key, json.loads(existing[0])
        since = (now - timedelta(days=7)).timestamp()
        rows = c.execute("SELECT occurrence,kind,origin,payload,recorded_at FROM secretary_events WHERE conversation='der-secretary' AND recorded_at>=? AND recorded_at<=? AND kind IN ('ENGINEERING_PROPOSAL','ENGINEERING_STATUS','READ_ONLY_EXPERIMENT','PUBLIC_RESEARCH_RESULT','TASK_RESULT','ENGINEERING_HANDOFF') ORDER BY recorded_at DESC LIMIT 16", (since, now.timestamp())).fetchall()
        runs = c.execute('SELECT r.state,count(*) FROM secretary_runs r JOIN secretary_events e ON e.occurrence=r.instruction WHERE e.conversation=? AND r.started_at>=? AND r.started_at<=? GROUP BY r.state', ('der-secretary', since, now.timestamp())).fetchall()
    evidence = []
    for occurrence, kind, origin, raw, recorded in rows:
        p = json.loads(raw)
        description = str(p.get('title') or p.get('summary') or p.get('state') or p.get('name') or (p.get('request',{}).get('name') if isinstance(p.get('request'),dict) else p.get('request')) or '归档记录，需读取详情')[:100]
        evidence.append(f'{occurrence[:90]} | {kind}/{origin} | {datetime.fromtimestamp(recorded, timezone.utc):%m-%d %H:%MZ} | {description}')
    from .market_clock import load_calendar
    calendar=load_calendar()
    calendar_status='；'.join(name+'至'+min(calendar['valid_through'],profile.get('valid_through',calendar['valid_through']))+('（'+profile['review_reason']+'）' if profile.get('review_reason') else '') for name,profile in calendar['profiles'].items())
    prompt = (f'买der秘书工程周报 · {year}-W{week:02d}\n'
              f'证据截止：{local:%Y-%m-%d %H:%M %Z}；仅最近7天归档，最多16条，不是全项目审计。\n'
              '请Codex先读AGENTS.md、PRODUCTION.md和当前项目上下文，在linked worktree核实并推进已授权事项。\n'
              '目标：价值投资指导的可验证量化研究、持仓管理和稳定运行。先核实P0：保护覆盖与原生回读、UNKNOWN对账、资金/汇率与外部敞口、全自动执行验收。不得把历史通过当作当前已收口。\n'
              '交易日历：'+calendar_status+'；下一年度/交易所规则变化须提前核验，不能只续日期。\n'
              '研究：质量/估值/安全边际、组合集中度与流动性、止损和移动保护校准、多标的历史与危机回测；明确数据来源、时间范围、幸存者/前视偏差、费用和样本外，不能编造几百年个股或ETF数据。\n'
              '按P0/P1列问题、证据、实施范围、验收标准及真正需要用户决定的参数。保留暂停、维护和权限边界；模型建议不是交易授权。大规模极端行情交易与放宽门禁留作后续讨论。\n'
              '本周运行状态计数（不是收益）：'+json.dumps(dict(runs), ensure_ascii=False)+'\n'
              '证据索引：\n'+ ('\n'.join(evidence) if evidence else '未找到上述类型记录；不得推定没有故障或研究已完成。')+'\n'
              '交接状态：提示已归档；未证明Codex已接受任务、自动部署或完成。')
    expiry=(local+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)
    data = dict(expires_at=expiry.timestamp(), prompt=prompt, reason=prompt[:3600], generated_at=now.isoformat(),
                evidence=evidence, window_start=(now-timedelta(days=7)).isoformat(),
                desktop_chat_wakeup_connected=False, grants_execution_permission=False)
    if not persist:
        return key, data
    # Competing producers may race: immutable first writer wins; never rewrite its evidence.
    try:
        archive.append(key, 'der-secretary', origin='SYSTEM', kind='ENGINEERING_WEEKLY', payload=data)
    except ValueError:
        with closing(archive.connect()) as c:
            row = c.execute("SELECT payload FROM secretary_events WHERE occurrence=? AND kind='ENGINEERING_WEEKLY'", (key,)).fetchone()
        if not row:
            raise
        data = json.loads(row[0])
    return key, data


def collect(archive, store, *, now=None):
    now = now or datetime.fromtimestamp(store.clock(), timezone.utc)
    local = now.astimezone(ZONE)
    # Sunday evening only. No Monday backfill of a missed previous week.
    if local.weekday() != 6 or local.hour < 18:
        return 0
    key, data = packet(archive, now, persist=True)
    with closing(store.connect()) as c, c:
        result = c.execute("INSERT OR IGNORE INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES(?,1,'ENGINEERING_WEEKLY',?,'PENDING')", (key, json.dumps(dict(data, queued_at=store.clock(), message_role='ENGINEERING'), ensure_ascii=False)))
        return result.rowcount
