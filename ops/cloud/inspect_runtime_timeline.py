"""Read-only saved-state timeline. No broker, network, send or service actions."""
import argparse
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo


def inspect(root, day, zone='Europe/Berlin'):
    root=Path(root).resolve();tz=ZoneInfo(zone);day=date.fromisoformat(str(day))
    begin=datetime.combine(day,time(),tz).timestamp()
    end=datetime.combine(day+timedelta(days=1),time(),tz).timestamp()
    def stamp(value):
        return datetime.fromtimestamp(value,tz).isoformat() if value is not None else None
    out=dict(day=day.isoformat(),timezone=zone,generated_at=datetime.now(timezone.utc).isoformat(),
             notices=[],pause_conditions=[],warnings=[])
    try:
        manifest=json.loads((root/'production.json').read_text())
        out['global_gate']=dict(paused=(root/'PAUSED').exists(),maintenance=(root/'runtime/MAINTENANCE').exists(),
            ready=manifest.get('ready'),mode=manifest.get('mode'),pause_started_at=None,
            note='Marker existence is current evidence; its filesystem time does not prove when business paused.')
    except (OSError,ValueError) as exc:
        out['warnings'].append('Global gate unavailable: '+type(exc).__name__)
    path=root/'runtime/recovery.sqlite3'
    try:
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2)) as c:
            c.execute('PRAGMA query_only=ON')
            rows=c.execute('SELECT n.id,n.incident_key,n.generation,n.kind,n.status,n.payload,r.payload,d.attempt_started_at,d.ack_received_at '
                'FROM notification_outbox n LEFT JOIN notification_receipts r ON r.notification_id=n.id '
                'LEFT JOIN notification_delivery d ON d.notification_id=n.id ORDER BY n.id DESC LIMIT 20000').fetchall()
            if len(rows)==20000:out['warnings'].append('Notification scan limit reached; older history may be omitted')
            for ident,key,generation,kind,status,payload,receipt,started,ack in reversed(rows):
                p=json.loads(payload);queued=p.get('queued_at')
                if queued is None or not begin<=queued<end:continue
                native=json.loads(receipt) if receipt else {}
                out['notices'].append(dict(id=ident,incident_key=key,generation=generation,kind=kind,status=status,
                    scope=p.get('scope'),reason=p.get('reason'),ib_error_code=p.get('ib_error_code'),symbol=p.get('symbol'),
                    queued_at=stamp(queued),started_at=stamp(started),ack_at=stamp(ack),
                    delay_seconds=round(ack-queued,3) if ack is not None else None,
                    message_ids=native.get('message_ids'),provider_dates=native.get('server_dates'),
                    transport=native.get('transport'),chat_id=native.get('chat_id')))
            try:
                groups={};total=0
                for payload,observed in c.execute("SELECT payload,observed FROM paper_callback_events WHERE kind='pause_transition' AND observed>=? AND observed<? ORDER BY observed LIMIT 20001",(begin,end)):
                    total+=1
                    if total>20000:out['warnings'].append('Pause condition scan limit reached');break
                    p=json.loads(payload);key=(p.get('action'),p.get('scope'),p.get('reason'))
                    g=groups.setdefault(key,dict(action=key[0],scope=key[1],reason=key[2],count=0,first_at=stamp(observed),last_at=None))
                    g['count']+=1;g['last_at']=stamp(observed)
                out['pause_conditions']=list(groups.values());out['pause_condition_event_count']=min(total,20000)
                raw=c.execute('SELECT payload FROM paper_safety_state WHERE id=1').fetchone()
                if raw:
                    s=json.loads(raw[0]);out['current_monitor']=dict(connected=s.get('connected'),upstream_connected=s.get('upstream_connected'),
                        identity=s.get('identity'),fault=s.get('fault'),pauses=s.get('pause_scopes',{}).get('pauses',[]))
            except (sqlite3.Error,ValueError) as exc:out['warnings'].append('Pause history unavailable: '+type(exc).__name__)
    except (sqlite3.Error,ValueError) as exc:out['warnings'].append('Notification history unavailable: '+type(exc).__name__)
    return out


def markdown(data):
    def cell(value):return str(value if value is not None else '未记录').replace('|','／').replace('\n','；')
    lines=['# 云端今日运行与 Telegram 对照', '',data['day']+'｜'+data['timezone'], '',
           '服务停启、业务暂停条件、通知发送是三类证据。Telegram ACCEPTED 表示平台接受，不代表用户已读。', '',
           '## 当前全局交易门禁', '',cell(data.get('global_gate')), '',
           '暂停最初设置时间未获历史证据，不能把文件修改时间或 Gateway 停启时间当作策略暂停时间。', '',
           '## 今日通知账本', '', '| 排队/故障记录时间 | 类型 / 原因 | Telegram确认时间 | 消息编号 | 结果 |',
           '| --- | --- | --- | --- | --- |']
    for n in data['notices']:
        reason=(n.get('reason') or '')[:220]
        lines.append('| '+' | '.join(cell(v) for v in (n['queued_at'],n['kind']+' / '+reason,n['ack_at'],n['message_ids'],n['status']))+' |')
    lines+=['', '没有消息编号/原生回执时不能说 Telegram 已接收。记录时间不是精确的底层故障起点。', '',
            '## 暂停条件变化（聚合，不能当作停机次数）', '',
            '条件事件数：'+str(data.get('pause_condition_event_count','未知')), '',
            '| 首次观测 | 最后观测 | 条件 / 动作 | 同条件记录数 |', '| --- | --- | --- | --- |']
    for p in data['pause_conditions']:
        lines.append('| '+' | '.join(cell(v) for v in (p['first_at'],p['last_at'],p['scope']+' / '+p['action']+' / '+p['reason'],p['count']))+' |')
    if data['warnings']:lines+=['','## 来源缺口','']+['- '+w for w in data['warnings']]
    return '\n'.join(lines)+'\n'


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--state-root',type=Path,required=True)
    p.add_argument('--day',required=True);p.add_argument('--timezone',default='Europe/Berlin');p.add_argument('--markdown',action='store_true')
    a=p.parse_args();d=inspect(a.state_root,a.day,a.timezone)
    print(markdown(d) if a.markdown else json.dumps(d,ensure_ascii=False,indent=2))
    return 2 if d['warnings'] else 0

if __name__=='__main__':raise SystemExit(main())
