"""Reviewed exchange schedules for awareness, never execution permission or API health."""
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

MANIFEST = Path(__file__).resolve().parents[1] / 'config/market_awareness_calendar.json'
BERLIN = ZoneInfo('Europe/Berlin')


def load_calendar(path=MANIFEST):
    raw = Path(path).read_bytes()
    data = json.loads(raw)
    data['fingerprint'] = hashlib.sha256(raw).hexdigest()
    return data


def closure(data, profile, day):
    through=min(data['valid_through'],profile.get('valid_through',data['valid_through']))
    if not data['valid_from'] <= day.isoformat() <= through:
        return '日历未核验'
    return ('周末' if day.weekday() >= 5 else
            data['calendars'][profile['calendar']]['holidays'].get(day.isoformat()))


def boundaries(data, profile, day):
    if closure(data, profile, day):
        return []
    cal = data['calendars'][profile['calendar']]
    phases = profile.get('early_phases', profile['phases']) if day.isoformat() in cal['early_closes'] else profile['phases']
    zone = ZoneInfo(profile['timezone'])
    return [(datetime.combine(day, time.fromisoformat(t), zone), code, label)
            for t, code, label in phases]


def upcoming(data, profile, day):
    closed = []
    for offset in range(1, 16):
        future = day + timedelta(days=offset)
        reason = closure(data, profile, future)
        if reason == '日历未核验':
            return closed, None
        if reason:
            closed.append(f'{future:%m-%d} {reason}')
        else:
            return closed, boundaries(data, profile, future)[0][0]
    return closed, None


def snapshot(venue, now, data=None):
    if now.tzinfo is None:
        raise ValueError('Timezone-aware timestamp required')
    data = data or load_calendar()
    profile = data['profiles'][venue]
    local = now.astimezone(ZoneInfo(profile['timezone']))
    day = local.date()
    reason = closure(data, profile, day)
    states = boundaries(data, profile, day)
    code, label, start = 'CLOSED', '尚未开市', datetime.combine(day, time(), local.tzinfo)
    for boundary, phase, description in states:
        if boundary <= local:
            code, label, start = phase, description, boundary
    if reason:
        code, label = ('UNKNOWN', reason) if reason == '日历未核验' else ('HOLIDAY', '休市：' + reason)
    next_boundary = next((b for b, _, _ in states if b > local), None)
    closed, next_open = upcoming(data, profile, day)
    if reason and reason != '日历未核验':
        closed.insert(0, f'{day:%m-%d} {reason}')
    if next_boundary is None:
        next_boundary = next_open
    occurrence = (f'{venue}:UNKNOWN:{data["fingerprint"][:12]}' if code=='UNKNOWN' else
                  f'{venue}:{day}:{start:%H%M%S}:{code}:{data["fingerprint"][:12]}')
    text = f'🕒 {profile["label"]}｜{label}\n柏林 {now.astimezone(BERLIN):%m-%d %H:%M} · 当地 {local:%H:%M %Z}'
    # At core close announce upcoming holidays immediately, not only after post-market ends.
    closing = code in ('POST', 'CLOSE_AUCTION', 'CLOSE_UNCROSS', 'CLOSED', 'HOLIDAY')
    if closing and closed:
        text += '\n后续休市：' + '；'.join(closed)
    if closing and closed and next_open:
        text += '\n下次开市：柏林 ' + next_open.astimezone(BERLIN).strftime('%m-%d %H:%M')
    if next_boundary:
        text += '\n下一阶段：柏林 ' + next_boundary.astimezone(BERLIN).strftime('%m-%d %H:%M')
    elif code == 'UNKNOWN' or closing:
        text += '\n下一开市待核验。'
    if code in ('OPEN_AUCTION', 'CORE', 'CLOSE_AUCTION') and venue == 'ETFPLUS':
        text += '\n集合竞价结束含最多30秒随机窗口；以交易所实际状态为准。'
    text += '\n仅日历提示；API连接、临时停牌与交易权限独立监测。'
    midnight=datetime.combine(day+timedelta(days=1),time(),local.tzinfo)
    expires=min(midnight,next_boundary) if next_boundary else midnight
    return dict(expires_at=expires.timestamp() if code!='UNKNOWN' else None, venue=venue, phase=code, occurrence=occurrence, reason=text,
                source_version=data['fingerprint'], verified_on=data['verified_on'],
                valid_through=min(data['valid_through'],profile.get('valid_through',data['valid_through'])), next_boundary=next_boundary.isoformat() if next_boundary else None,
                grants_trading_permission=False)


def collect(store, *, now=None, data=None):
    """Atomic cursor/outbox: reserve no transports, and never replay missed phases."""
    now = now or datetime.fromtimestamp(store.clock(), timezone.utc)
    data = data or load_calendar()
    count = 0
    with closing(store.connect()) as c, c:
        c.execute('BEGIN IMMEDIATE')
        for venue in data['profiles']:
            state = snapshot(venue, now, data)
            through=state['valid_through']
            remaining=(date.fromisoformat(through)-now.astimezone(ZoneInfo(data['profiles'][venue]['timezone'])).date()).days
            if 0<=remaining<=14:
                review_key='calendar-review:'+venue+':'+through+':'+data['fingerprint'][:12]
                detail=data['profiles'][venue].get('review_reason','核验下一年度官方日历与时段')
                review=dict(reason='🕒 '+data['profiles'][venue]['label']+'时段规则需要复核｜当前核验至 '+through+'。'+detail+'。已列入每周工程复盘；过期后不猜测开市时间。',severity='YELLOW',message_role='CALENDAR',queued_at=store.clock(),grants_trading_permission=False)
                c.execute("INSERT OR IGNORE INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES(?,1,'MARKET_SESSION',?,'PENDING')",(review_key,json.dumps(review,ensure_ascii=False)))
                count+=c.execute('SELECT changes()').fetchone()[0]
            key = 'market-clock:' + venue
            prior = c.execute('SELECT payload FROM incident_cursors WHERE source=?', (key,)).fetchone()
            previous = json.loads(prior[0]) if prior else None
            # The cursor tracks every observation, not just the last transition.
            if previous and now.timestamp() < previous['observed']:
                continue
            if previous and previous['occurrence'] == state['occurrence']:
                previous['observed']=now.timestamp()
                c.execute('INSERT OR REPLACE INTO incident_cursors VALUES(?,?)',(key,json.dumps(previous,ensure_ascii=False)))
                continue
            state['observed'] = now.timestamp()
            if previous and now.timestamp() - previous['observed'] > 180:
                state['reason'] += '\n观察有间断，以上为当前时段；未补发过期提醒。'
            # Only unsent stale notices can be superseded; attempted outcomes stay untouched.
            c.execute("UPDATE notification_outbox SET status='SUPERSEDED' WHERE kind='MARKET_SESSION' AND status='PENDING' AND json_extract(payload,'$.venue')=? AND incident_key!=?", (venue,'market-session:'+state['occurrence']))
            payload = dict(state, message_role='CALENDAR', queued_at=store.clock(), severity='YELLOW' if state['phase']=='UNKNOWN' else 'INFO')
            c.execute("INSERT OR IGNORE INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES(?,1,'MARKET_SESSION',?,'PENDING')",
                      ('market-session:' + state['occurrence'], json.dumps(payload, ensure_ascii=False)))
            count += c.execute('SELECT changes()').fetchone()[0]
            c.execute('INSERT OR REPLACE INTO incident_cursors VALUES(?,?)', (key, json.dumps(state, ensure_ascii=False)))
    return count
