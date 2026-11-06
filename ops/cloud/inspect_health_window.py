"""Read-only rolling health evidence. Observation spans are not outage durations."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo


def inspect(root, end, hours=24):
    if end.tzinfo is None or hours<=0:raise ValueError('Timezone-aware end and positive hours required')
    stop=end.timestamp();start=stop-hours*3600
    out=dict(begin=start,end=stop,events=[],samples=[],gaps=[],warnings=[],duration_semantics='Observation timestamps only; exact outage boundaries UNKNOWN unless separately recorded')
    path=Path(root).resolve()/'runtime/recovery.sqlite3'
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=3)) as c:
        c.execute('PRAGMA query_only=ON')
        for table,key in [('runtime_health_samples','samples'),('runtime_health_events','events')]:
            try:
                c.row_factory=sqlite3.Row
                out[key]=[dict(r) for r in c.execute('SELECT * FROM '+table+' WHERE observed>=? AND observed<? ORDER BY observed',(start,stop))]
            except sqlite3.OperationalError as e:
                if 'no such table' not in str(e):raise
                out['warnings'].append(table+' unavailable; historical coverage UNKNOWN')
        groups={}
        for row in out['samples']:groups.setdefault(row['source'],[]).append(row)
        for source,rows in groups.items():
            previous=start;epoch=None;limit=90 if source=='paper-safety' else 390
            for row in rows:
                if row['observed']-previous>limit or (epoch is not None and row['epoch']!=epoch):
                    out['gaps'].append(dict(source=source,begin=previous,end=row['observed'],state='UNKNOWN'))
                previous=row['observed'];epoch=row['epoch']
            if stop-previous>limit:out['gaps'].append(dict(source=source,begin=previous,end=stop,state='UNKNOWN'))
        for source in ('paper-safety','host-status'):
            if source not in groups:out['gaps'].append(dict(source=source,begin=start,end=stop,state='UNKNOWN'))
    return out


def markdown(data):
    def stamp(t):return datetime.fromtimestamp(t,ZoneInfo('Europe/Berlin')).isoformat(timespec='seconds')
    lines=['# 四项运行监测（滚动窗口）','',stamp(data['begin'])+' — '+stamp(data['end']),'',
           '状态变化时间是观测时间；精确断开/恢复边界和未覆盖区间为 UNKNOWN。会话 VERIFIED 仅代表本程序身份及上游证据，不代表可枚举所有登录设备。云端自报不能证明整机离线时外部告警有效。','',
           '| 观测时间 | 来源 / 项目 | 前状态 → 当前状态 |','| --- | --- | --- |']
    for r in data['events']:
        lines.append('| '+stamp(r['observed'])+' | '+r['source']+' / '+r['dimension']+' | '+r['previous']+' → '+r['state']+' |')
    lines+=['','## 无覆盖区间','', '| 来源 | 起点 | 终点 | 跨度（不等于故障时长） |','| --- | --- | --- | --- |']
    for g in data['gaps']:lines.append('| '+g['source']+' | '+stamp(g['begin'])+' | '+stamp(g['end'])+' | '+str(round(g['end']-g['begin'],3))+'秒 UNKNOWN |')
    return '\n'.join(lines+['']+data['warnings'])+'\n'


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--state-root',type=Path,required=True)
    p.add_argument('--end',help='ISO timestamp with timezone; defaults to now UTC');p.add_argument('--hours',type=float,default=24)
    p.add_argument('--markdown',action='store_true');a=p.parse_args()
    end=datetime.fromisoformat(a.end.replace('Z','+00:00')) if a.end else datetime.now(timezone.utc)
    data=inspect(a.state_root,end,a.hours);print(markdown(data) if a.markdown else json.dumps(data,indent=2))
    return 2 if data['warnings'] else 0

if __name__=='__main__':raise SystemExit(main())
