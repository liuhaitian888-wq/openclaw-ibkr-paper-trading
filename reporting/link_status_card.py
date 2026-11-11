"""One fixed host-owned link card; local reads only, independent pin outcome."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

SOURCE_THREAD = '01a1c257-2703-7653-a2a5-4ab583256cf4'
SOURCE_MESSAGE = '01a1c869-090b-7b62-8bb4-7c8850b54d4c'
SCOPE = 'current-link-status-20261111-v1'
KEY = 'link-status:current'


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def sha(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def initialize(store):
    with closing(store.connect()) as c, c:
        c.executescript('''CREATE TABLE IF NOT EXISTS link_status_scope (
          id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS link_status_versions (
          notification_id INTEGER PRIMARY KEY, generation INTEGER NOT NULL,
          payload_sha256 TEXT NOT NULL, recorded_at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS link_status_state (
          id INTEGER PRIMARY KEY CHECK(id=1), message_id INTEGER,
          pin_state TEXT NOT NULL DEFAULT 'NOT_ATTEMPTED', updated_at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS link_status_pin_events (
          id INTEGER PRIMARY KEY, state TEXT NOT NULL, message_id INTEGER NOT NULL,
          recorded_at REAL NOT NULL, payload TEXT NOT NULL);''')


def authorize(store, config, *, source_thread, source_message, native_proof=None):
    """Operator-only entry; never a secretary/model tool. Authority is exact.

    A reuse proof must bind a preexisting accepted bot receipt and independently
    read native author/target/body. The operator owns that native read.
    """
    from .publication_policy import enabled
    if not enabled(config) or (source_thread, source_message) != (SOURCE_THREAD, SOURCE_MESSAGE):
        raise PermissionError('Exact human current-link-card authorization required')
    initialize(store)
    message_id = None
    with closing(store.connect()) as c, c:
        c.execute('BEGIN IMMEDIATE')
        if native_proof is not None:
            message_id = native_proof.get('message_id')
            if (native_proof.get('chat_id') != config['chat_id']
                    or native_proof.get('author_id') != config['bot_id']
                    or type(message_id) is not int or message_id <= 0
                    or native_proof.get('source') != 'native_owner_readback'
                    or not isinstance(native_proof.get('body_sha256'), str)
                    or len(native_proof['body_sha256']) != 64):
                raise PermissionError('Exact native bot card proof required')
            found = False
            for raw, in c.execute('''SELECT r.payload FROM notification_receipts r
              JOIN notification_outbox n ON n.id=r.notification_id
              WHERE n.status='TELEGRAM_ACCEPTED' AND n.kind='AUTOMATIC_STATUS'
              ORDER BY n.id DESC LIMIT 100'''):
                r = json.loads(raw)
                if (r.get('chat_id') == config['chat_id'] and r.get('message_ids') == [message_id]
                        and r.get('card_format') == 'compact-v1'):
                    found = True
            if not found:
                raise PermissionError('Reuse requires matching accepted original bot receipt')
        value = dict(scope=SCOPE, source_thread=source_thread, source_message=source_message,
                     chat_id=config['chat_id'], bot_id=config['bot_id'], native_proof=native_proof,
                     reuse_message_id=message_id)
        old = c.execute('SELECT payload FROM link_status_scope WHERE id=1').fetchone()
        if old and json.loads(old[0]) != value:
            raise PermissionError('Existing card scope cannot be replaced or expanded')
        c.execute('INSERT OR IGNORE INTO link_status_scope VALUES (1,?)', (encoded(value),))
        c.execute('INSERT OR IGNORE INTO link_status_state(id,message_id,updated_at) VALUES(1,?,?)',
                  (message_id, store.clock()))


def scope(c, config):
    r = c.execute('SELECT payload FROM link_status_scope WHERE id=1').fetchone()
    if not r:
        return None
    p = json.loads(r[0])
    return p if (p.get('scope') == SCOPE and p.get('source_thread') == SOURCE_THREAD
                 and p.get('source_message') == SOURCE_MESSAGE and p.get('chat_id') == config['chat_id']
                 and p.get('bot_id') == config['bot_id']) else None


def _fresh(value, now, age):
    return type(value) in (int, float) and math.isfinite(value) and 0 <= now-value <= age


def snapshot(store, root, now):
    """No sockets, model calls, systemctl, login, or broker requests."""
    root = Path(root)
    with closing(store.connect()) as c:
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        r = c.execute('SELECT payload FROM paper_safety_state WHERE id=1').fetchone() if 'paper_safety_state' in tables else None
        p = json.loads(r[0]) if r else {}
        from .automatic_notifications import persistence_clear
        persistence_ok = persistence_clear(store, c)
        obs = {k: json.loads(v) for k, v in c.execute('SELECT name,payload FROM module_observations LIMIT 100')} if 'module_observations' in tables else {}
    from .health import resolve_modules
    modules = resolve_modules(obs, now=datetime.fromtimestamp(now, timezone.utc))
    def module(name):
        row = modules.get(name, {})
        return '已核验' if row.get('state') == 'HEALTHY' and row.get('freshness') == 'FRESH' else '未就绪/证据陈旧' if row.get('state') in ('FAILED', 'OFFLINE', 'DEGRADED', 'WAITING_DEPENDENCY') else 'UNKNOWN'
    recent = _fresh(p.get('last_server_reply'), now, 10)
    # Heartbeats never date account snapshots. A persisted complete marker may
    # come from the native owner's state or its exact epoch-bound module bridge.
    reconciled=p.get('reconciled_at')
    if not _fresh(reconciled,now,30):
        bridge=[obs.get(name,{}) for name in ('POSITIONS','ORDERS','EXECUTIONS')]
        stamps=[row.get('reconciled_at') for row in bridge]
        reconciled=stamps[0] if (all(_fresh(stamp,now,30) for stamp in stamps)
            and len(set(stamps))==1 and p.get('epoch')
            and all(row.get('broker_epoch')==p['epoch'] for row in bridge)) else None
    business = (p.get('connected') is True and p.get('identity') is True
                and p.get('upstream_connected') is True and p.get('dirty') is False
                and set(p.get('ends', [])) == {'orders', 'completed_orders', 'executions', 'positions'}
                and recent and persistence_ok and _fresh(reconciled,now,30))
    codex = 'UNKNOWN；未见受限任务原生验收'
    path = root/'agent_secretary.sqlite3'
    if path.is_file():
        try:
            with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=.1)) as c:
                c.execute('PRAGMA query_only=ON')
                row = c.execute("SELECT 1 FROM secretary_events WHERE origin='SYSTEM' AND kind='ENGINEERING_NATIVE_RECEIPT' AND json_extract(payload,'$.stage')='TURN_COMPLETED' LIMIT 1").fetchone()
                if row:
                    codex = '历史受限只读任务已验；通用开发/部署未验'
        except (sqlite3.Error, ValueError):
            pass
    gates = '暂停/维护中' if (root/'PAUSED').exists() or (root/'runtime/MAINTENANCE').exists() else '未取得自动交易放行证据'
    tcp='近期API回执已核验' if recent and p.get('connected') is True else '未就绪/UNKNOWN（端口不等于业务就绪）'
    try:
        observer=root/'runtime/paper-observer.latest.json'
        if observer.is_symlink() or observer.stat().st_size>1_000_000:raise ValueError('Bounded local observer required')
        with observer.open() as handle:evidence=json.load(handle)
        at=datetime.fromisoformat(evidence['observed_at'].replace('Z','+00:00'))
        if (at.tzinfo is not None and _fresh(at.timestamp(),now,300)
                and evidence.get('environment')=='PAPER' and evidence.get('gateway_api_handshake') is True
                and not (recent and p.get('connected') is True)):
            tcp='近期协议握手已完成（observer）；账户另验'
    except (OSError,ValueError,TypeError,KeyError,AttributeError):
        pass
    return dict(tcp=tcp,
                account='新鲜完整账户回读已核验' if business else '未就绪；账户/完整回读证据未齐',
                data=module('MARKET_DATA'), model=module('SECRETARY_MODEL'),
                codex=codex, gates=gates)


def queue(store, root, config):
    from .publication_policy import enabled
    if not enabled(config):
        return 0
    initialize(store)
    now = store.clock()
    if 0 <= now-getattr(store, '_link_status_checked_at', float('-inf')) < 5:
        return 0
    current = snapshot(store, root, now)
    with closing(store.connect()) as c, c:
        c.execute('BEGIN IMMEDIATE')
        if not scope(c, config):
            return 0
        last = c.execute('''SELECT n.id,n.generation,n.payload,n.status,v.recorded_at
          FROM notification_outbox n JOIN link_status_versions v ON v.notification_id=n.id
          ORDER BY n.id DESC LIMIT 1''').fetchone()
        if last:
            if last[3] not in ('TELEGRAM_ACCEPTED', 'SUPPRESSED'):
                return 0  # PENDING/STARTED/UNKNOWN never creates a second card.
            old = json.loads(last[2])
            if now-last[4] < 60 or (old['links'] == current and now-last[4] < 300):
                store._link_status_checked_at = now
                return 0
        generation = last[1]+1 if last else 1
        p = dict(scope=SCOPE, source_message=SOURCE_MESSAGE, links=current,
                 observed_at=now, queued_at=now, grants_trading_permission=False)
        cur = c.execute("INSERT INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES(?,?,'LINK_STATUS_CARD',?,'PENDING')", (KEY, generation, encoded(p)))
        c.execute('INSERT INTO link_status_versions VALUES (?,?,?,?)', (cur.lastrowid, generation, sha(p), now))
    store._link_status_checked_at = now
    return 1


def valid(store, item, config):
    if item['kind'] != 'LINK_STATUS_CARD' or item['incident_key'] != KEY:
        return False
    initialize(store)
    with closing(store.connect()) as c:
        r = c.execute('SELECT generation,payload_sha256 FROM link_status_versions WHERE notification_id=?', (item['id'],)).fetchone()
        authorized = scope(c, config)
        last = c.execute('SELECT max(notification_id) FROM link_status_versions').fetchone()[0]
    p = item['payload']
    return bool(authorized and r == (item['generation'], sha(p)) and last == item['id']
                and p.get('scope') == SCOPE and p.get('grants_trading_permission') is False
                and _fresh(p.get('observed_at'), store.clock(), 360)
                and p.get('links') == snapshot(store, store.path.parent.parent, store.clock()))


def render(item):
    p = item['payload']; s = p['links']
    labels = [('tcp', 'API/TCP'), ('account', '业务账户'), ('data', '行情新鲜度'),
              ('model', '模型链路'), ('codex', 'Codex'), ('gates', '交易门禁')]
    return '当前 API 与各链路状态\n'+'\n'.join(label+'：'+s[key] for key, label in labels)+'\n核对时间（柏林）：'+datetime.fromtimestamp(p['observed_at'], ZoneInfo('Europe/Berlin')).strftime('%Y-%m-%d %H:%M:%S')+'\n普通事件后台存档；日报附件和研究成果发布到群。'


def message_id(store):
    initialize(store)
    with closing(store.connect()) as c:
        r = c.execute('SELECT message_id FROM link_status_state WHERE id=1').fetchone()
        if r and r[0] is not None:return r[0]
        # A crash after immutable ACCEPTED evidence but before the local card
        # projection must reconcile the exact receipt, never send a replacement.
        scope_row=c.execute('SELECT payload FROM link_status_scope WHERE id=1').fetchone()
        latest=c.execute('''SELECT r.payload FROM notification_receipts r
          JOIN notification_outbox n ON n.id=r.notification_id
          JOIN link_status_versions v ON v.notification_id=n.id
          WHERE n.status='TELEGRAM_ACCEPTED' ORDER BY n.id DESC LIMIT 1''').fetchone()
        if scope_row and latest:
            expected=json.loads(scope_row[0]);receipt=json.loads(latest[0]);ids=receipt.get('message_ids',[])
            if receipt.get('chat_id')==expected.get('chat_id') and len(ids)==1 and type(ids[0]) is int and ids[0]>0:
                return ids[0]
    return None


def accepted(store, item, config, receipt):
    # Reconcile immutable native delivery even if business state changed after
    # wire. A changed business state requires a new EDIT, never a second SEND.
    initialize(store)
    with closing(store.connect()) as c:
        r=c.execute('SELECT generation,payload_sha256 FROM link_status_versions WHERE notification_id=?',(item['id'],)).fetchone()
        authorized=scope(c,config)
    if not authorized or r!=(item['generation'],sha(item['payload'])) or receipt.get('chat_id') != config['chat_id'] or len(receipt.get('message_ids', [])) != 1:
        raise PermissionError('Exact accepted status card receipt required')
    ident = receipt['message_ids'][0]
    with closing(store.connect()) as c, c:
        old = c.execute('SELECT message_id FROM link_status_state WHERE id=1').fetchone()
        if old and old[0] is not None and old[0] != ident:
            raise PermissionError('Status card identity cannot change')
        c.execute('UPDATE link_status_state SET message_id=?,updated_at=? WHERE id=1', (ident, store.clock()))


def pin_event(store, ident, state, payload=None):
    with closing(store.connect()) as c, c:
        c.execute('INSERT INTO link_status_pin_events(state,message_id,recorded_at,payload) VALUES(?,?,?,?)',
                  (state, ident, store.clock(), encoded(payload or {})))
        c.execute('UPDATE link_status_state SET pin_state=?,updated_at=? WHERE id=1', (state, store.clock()))


async def ensure_pin(store, bot, config):
    import asyncio
    try:
        async with asyncio.timeout(10):
            return await _ensure_pin(store,bot,config)
    except TimeoutError:
        # A reserved wire attempt must retain uncertainty even on cancellation.
        initialize(store)
        with closing(store.connect()) as c:
            r=c.execute('SELECT message_id,pin_state FROM link_status_state WHERE id=1').fetchone()
        if r and r[1]=='STARTED':pin_event(store,r[0],'UNKNOWN')
        return 'UNKNOWN' if r and r[1]=='STARTED' else 'PREFLIGHT_UNAVAILABLE'


async def _ensure_pin(store, bot, config):
    """Existing sender bot only; missing rights blocks without a wire attempt."""
    initialize(store)
    with closing(store.connect()) as c:
        authorized = scope(c, config)
        r = c.execute('SELECT message_id,pin_state FROM link_status_state WHERE id=1').fetchone()
        last=c.execute('''SELECT n.status FROM notification_outbox n JOIN link_status_versions v ON v.notification_id=n.id ORDER BY n.id DESC LIMIT 1''').fetchone()
    if not authorized or not r or r[0] is None or not last or last[0]!='TELEGRAM_ACCEPTED':
        return 'NO_CARD'
    ident, state = r
    now=store.clock()
    if 0<=now-getattr(store,'_link_pin_checked_at',float('-inf'))<60:return state
    store._link_pin_checked_at=now
    try:
        chat = await bot.get_chat(config['chat_id'], read_timeout=10, connect_timeout=5)
        if chat.id!=config['chat_id']:raise PermissionError('Native group mismatch')
        pinned = getattr(chat, 'pinned_message', None)
        if pinned and pinned.message_id == ident:
            pin_event(store, ident, 'PINNED', {'proof': 'native_get_chat'})
            return 'PINNED'
        if state in ('PINNED','DRIFT'):
            if state!='DRIFT':pin_event(store,ident,'DRIFT',{'proof':'native_pin_no_longer_current'})
            return 'DRIFT'  # Observe drift; never fight another owner by repinning.
        if state in ('STARTED', 'OWNER_STARTED', 'UNKNOWN'):
            return state  # A missing pin does not prove an uncertain attempt failed.
        member = await bot.get_chat_member(config['chat_id'], config['bot_id'], read_timeout=10, connect_timeout=5)
        if member.user.id!=config['bot_id']:raise PermissionError('Native bot membership mismatch')
        if member.status != 'administrator' or getattr(member, 'can_pin_messages', False) is not True:
            if state != 'BLOCKED_PERMISSION':
                pin_event(store, ident, 'BLOCKED_PERMISSION')
            return 'BLOCKED_PERMISSION'
        with closing(store.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            current = c.execute('SELECT pin_state FROM link_status_state WHERE id=1').fetchone()[0]
            if current in ('STARTED', 'OWNER_STARTED', 'UNKNOWN', 'PINNED'):
                return current
            # Reserve before the native side effect, independently of delivery.
            c.execute("UPDATE link_status_state SET pin_state='STARTED' WHERE id=1")
            c.execute("INSERT INTO link_status_pin_events(state,message_id,recorded_at,payload) VALUES('STARTED',?,?,'{}')", (ident, store.clock()))
        try:
            result = await bot.pin_chat_message(config['chat_id'], ident, disable_notification=True,
                                                read_timeout=15, connect_timeout=5)
            if result is not True:
                raise RuntimeError('Missing native pin acknowledgement')
        except Exception:
            pin_event(store, ident, 'UNKNOWN')
            return 'UNKNOWN'
        pin_event(store, ident, 'PINNED', {'proof': 'native_pin_ack'})
        return 'PINNED'
    except Exception:
        return 'PREFLIGHT_UNAVAILABLE'


def reserve_owner_pin(store, config, ident):
    """Exact operator bridge for the already-authorized owner native session.

    Returns False for all prior/uncertain attempts; never called by a model.
    Caller MUST verify native get_me/group/message author+body before calling.
    """
    initialize(store)
    with closing(store.connect()) as c,c:
        c.execute('BEGIN IMMEDIATE')
        r=c.execute('SELECT message_id,pin_state FROM link_status_state WHERE id=1').fetchone()
        latest=c.execute('''SELECT n.status FROM notification_outbox n JOIN link_status_versions v ON v.notification_id=n.id ORDER BY n.id DESC LIMIT 1''').fetchone()
        if not scope(c,config) or not r or type(ident) is not int or r[0]!=ident or latest!=('TELEGRAM_ACCEPTED',):
            raise PermissionError('Exact accepted host card required')
        if r[1] not in ('NOT_ATTEMPTED','BLOCKED_PERMISSION'):return False
        c.execute("UPDATE link_status_state SET pin_state='OWNER_STARTED' WHERE id=1")
        c.execute("INSERT INTO link_status_pin_events(state,message_id,recorded_at,payload) VALUES('OWNER_STARTED',?,?,'{}')",(ident,store.clock()))
    return True


def finish_owner_pin(store, config, ident, *, native_pinned_id):
    """Record positive native readback or retain UNKNOWN; not a retry grant."""
    initialize(store)
    with closing(store.connect()) as c:
        r=c.execute('SELECT message_id,pin_state FROM link_status_state WHERE id=1').fetchone()
        if not scope(c,config) or not r or r[0]!=ident or r[1] not in ('OWNER_STARTED','UNKNOWN','PINNED'):
            raise PermissionError('Reserved exact owner pin required')
    pin_event(store,ident,'PINNED' if type(native_pinned_id) is int and native_pinned_id==ident else 'UNKNOWN',{'proof':'native_owner_readback'})
