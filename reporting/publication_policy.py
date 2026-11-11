"""Host-owned publication decisions. Ordinary events stay in the durable archive."""
from contextlib import closing
import hashlib
import json

POLICY = 'publication-v2'
LIMIT = 500


def enabled(config):
    return config.get('automatic_notification_policy') == POLICY


def digest(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def decision(item, config):
    p = item['payload']; kind = item['kind']; key = item['incident_key']
    def route(audience, reason, view=None):
        return dict(policy_version=POLICY, audience=audience, reason=reason, public_view=view)
    if p.get('test_only') in (True, 1) or p.get('scope') == 'NOTIFICATION_CHANNEL_TEST':
        return route('archive', 'test_evidence_only')
    if kind == 'LINK_STATUS_CARD':
        # This is a candidate view, never authority: validate() MUST bind the
        # exact host registry before claim and twice before any wire operation.
        return route('group', 'registered_host_link_status', 'link_status_card')
    if (key == 'storage-capacity' and kind == 'ALERT' and p.get('scope') == 'CAPACITY'
            and p.get('severity') == 'RED' and p.get('private_notice') is True
            and p.get('requires_response') is True and isinstance(p.get('capacity'),dict)
            and type(p['capacity'].get('level')) is int and p['capacity']['level'] == 2):
        return route('owner', 'host_capacity_critical_requires_action', 'capacity_action')
    if kind in ('REPORT_BUNDLE', 'REPORT_SUPPLEMENT'):
        if not p.get('png_artifacts') or not p.get('included_reports'):
            return route('archive', 'report_status_is_not_a_report')
        return route('group', 'authorized_complete_account_report')
    if kind == 'SECRETARY_REPLY':
        if p.get('private_notice') is True or p.get('fixed_public_status') is True:
            return route('archive', 'delivery_or_activity_event_only')
        if p.get('completed_research') is True:
            from .notification_access import sensitive
            if not sensitive({'reason': p.get('reason', '')}):
                return route('group', 'registered_completed_research', 'research_result')
        # Native user questions remain private, irrespective of model labels.
        if p.get('native_owner_reply') is True or (key.startswith('secretary-ack:')
                and p.get('message_role') == 'ACK' and isinstance(p.get('instruction'), str)):
            return route('owner', 'native_owner_interaction')
        return route('archive', 'ordinary_automatic_activity')
    if (kind == 'AUTH_SESSION_EVENT' and key.startswith('gateway-session:')
            and p.get('phase') == 'OPERATOR'
            and p.get('source') == 'existing Gateway owner journal'):
        return route('owner', 'native_gateway_requires_human_action')
    if (key.startswith('paper-safety:protection:') and kind in
            ('ALERT', 'PROTECTION_UNPROTECTED', 'PROTECTION_PARTIALLY_PROTECTED', 'ESCALATION_RED')
            and p.get('severity') == 'RED'
            and p.get('protection_status') in ('UNPROTECTED', 'PARTIALLY_PROTECTED')):
        return route('owner', 'confirmed_protection_gap_requires_action')
    return route('archive', 'ordinary_event_archived_without_push')


def initialize(store):
    with closing(store.connect()) as c, c:
        c.executescript('''CREATE TABLE IF NOT EXISTS publication_archive (
          notification_id INTEGER PRIMARY KEY, policy TEXT NOT NULL, reason TEXT NOT NULL,
          payload_sha256 TEXT NOT NULL, recorded_at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS publication_research (
          notification_id INTEGER PRIMARY KEY, run TEXT NOT NULL, result_event TEXT NOT NULL,
          payload_sha256 TEXT NOT NULL);''')


def register_research(store, ident, payload, *, run, result_event, connection=None):
    """Queue owner calls only after a successful immutable MODEL research result."""
    def write(c):
        value=(run,result_event,digest(payload))
        prior=c.execute('SELECT run,result_event,payload_sha256 FROM publication_research WHERE notification_id=?',(ident,)).fetchone()
        if prior and prior!=value:raise PermissionError('Research identity cannot change')
        c.execute('INSERT OR IGNORE INTO publication_research VALUES (?,?,?,?)',(ident,*value))
    if connection is not None:
        write(connection)  # The queue transaction owns this borrowed connection.
    else:
        initialize(store)
        with closing(store.connect()) as c, c:write(c)


def validate(store, item, config):
    if not enabled(config):
        return True
    with closing(store.connect()) as c:
        row=c.execute('SELECT kind,incident_key,generation,payload,status FROM notification_outbox WHERE id=?',(item['id'],)).fetchone()
    if (not row or row[:3]!=(item['kind'],item['incident_key'],item['generation'])
            or json.loads(row[3])!=item['payload'] or row[4] not in ('PENDING','STARTED')):
        return False
    route = decision(item, config)
    if route['audience'] == 'archive':
        return False
    if item['kind'] == 'REPORT_SUPPLEMENT':
        from .report_schedule import quiet_supplement_valid
        return quiet_supplement_valid(store,item)
    if item['kind'] == 'LINK_STATUS_CARD':
        from .link_status_card import valid
        return valid(store, item, config)
    if route['public_view'] == 'capacity_action':
        return capacity_valid(store, item)
    if route['reason'] in ('native_gateway_requires_human_action','confirmed_protection_gap_requires_action'):
        with closing(store.connect()) as c:
            cutover=c.execute("SELECT payload FROM incident_cursors WHERE source='publication-v2:installed'").fetchone()
        from .link_status_card import _fresh
        p=item['payload']
        if not cutover or item['id']<=json.loads(cutover[0])['cutover_id'] or not _fresh(p.get('queued_at'),store.clock(),180):return False
        if route['reason']=='native_gateway_requires_human_action':
            return _fresh(p.get('observed_at'),store.clock(),180)
        with closing(store.connect()) as c:
            live=c.execute('SELECT generation,state FROM incidents WHERE incident_key=?',(item['incident_key'],)).fetchone()
            last=c.execute('SELECT max(id) FROM notification_outbox WHERE incident_key=?',(item['incident_key'],)).fetchone()[0]
        return live==(item['generation'],'OPEN') and last==item['id']
    if route['public_view'] == 'research_result':
        initialize(store)
        with closing(store.connect()) as c:
            r = c.execute('SELECT run,result_event,payload_sha256 FROM publication_research WHERE notification_id=?',
                          (item['id'],)).fetchone()
        return bool(r and r[0] == item['payload'].get('run') and r[2] == digest(item['payload']))
    return True


def capacity_valid(store, item):
    """Bind critical numbers to producer's atomic event/cursor and fresh sample."""
    try:
        from .capacity import public_status
        if public_status(item) is None:return False
        with closing(store.connect()) as c:
            cursor=c.execute("SELECT payload FROM incident_cursors WHERE source='capacity-v1'").fetchone()
            event=c.execute('SELECT payload FROM incident_events WHERE event_id=? AND incident_key=\'storage-capacity\'',('storage-capacity:'+str(item['generation']),)).fetchone()
        if not cursor or json.loads(cursor[0])!={'level':2,'sequence':item['generation']} or not event or json.loads(event[0])!=item['payload']:
            return False
        path=store.path.parent/'capacity.json'
        if path.is_symlink() or path.stat().st_size>2_000_000:return False
        with path.open() as handle:data=json.load(handle)
        from .link_status_card import _fresh
        return data.get('risk',{}).get('level')==2 and _fresh(data['samples'][-1]['at'],store.clock(),900)
    except (ImportError,OSError,ValueError,TypeError,KeyError,IndexError):
        return False


def _archive(c, item, now, reason, expected):
    from .automatic_notifications import _safe_unsent
    if not _safe_unsent(c, item['id']):
        return False
    raw = c.execute('SELECT kind,payload,incident_key,status FROM notification_outbox WHERE id=?',
                    (item['id'],)).fetchone()
    # Producers use different JSON encodings: compare semantics, not spacing.
    if not raw or raw[3] != expected or raw[0] != item['kind'] or raw[2] != item['incident_key'] or json.loads(raw[1]) != item['payload']:
        return False
    c.execute('INSERT OR IGNORE INTO publication_archive VALUES (?,?,?,?,?)',
              (item['id'], POLICY, reason, digest(item['payload']), now))
    return bool(c.execute("UPDATE notification_outbox SET status='SUPPRESSED' WHERE id=? AND status=?",
                          (item['id'], expected)).rowcount)


def archive_claimed(store, item, config):
    """Only a reserved but proven zero-wire row; never absorbs an operation."""
    initialize(store)
    reason = decision(item, config)['reason']
    with closing(store.connect()) as c, c:
        c.execute('BEGIN IMMEDIATE')
        c.execute("INSERT OR IGNORE INTO incident_cursors VALUES ('publication-v2:installed',?)", (json.dumps(dict(cutover_id=c.execute('SELECT coalesce(max(id),0) FROM notification_outbox').fetchone()[0],installed_at=store.clock())),))
        return _archive(c, item, store.clock(), reason, 'STARTED')


def prepare(store, config):
    if not enabled(config):
        return 0
    initialize(store)
    count = 0
    with closing(store.connect()) as c, c:
        c.execute('BEGIN IMMEDIATE')
        # Cursor bounds each pass without starving newer entries behind retained
        # PENDING operation reservations. A subsequent pass rotates to the start.
        c.execute("INSERT OR IGNORE INTO incident_cursors VALUES ('publication-v2:installed',?)", (json.dumps(dict(cutover_id=c.execute('SELECT coalesce(max(id),0) FROM notification_outbox').fetchone()[0],installed_at=store.clock())),))
        installed=json.loads(c.execute("SELECT payload FROM incident_cursors WHERE source='publication-v2:installed'").fetchone()[0])
        r = c.execute("SELECT payload FROM incident_cursors WHERE source='publication-v2:archive-cursor'").fetchone()
        after = json.loads(r[0]) if r else 0
        rows = c.execute("SELECT id,kind,incident_key,payload FROM notification_outbox WHERE status='PENDING' ORDER BY CASE WHEN id>? THEN 0 ELSE 1 END,id LIMIT ?", (after, LIMIT)).fetchall()
        for ident, kind, key, raw in rows:
            item = dict(id=ident, kind=kind, incident_key=key, payload=json.loads(raw))
            route = decision(item, config)
            old_action=(route['reason'] in ('native_gateway_requires_human_action','confirmed_protection_gap_requires_action') and ident<=installed['cutover_id'])
            if route['audience'] == 'archive' or old_action:
                count += _archive(c, item, store.clock(), route['reason'], 'PENDING')
        if rows:
            c.execute("INSERT INTO incident_cursors VALUES ('publication-v2:archive-cursor',?) ON CONFLICT(source) DO UPDATE SET payload=excluded.payload", (json.dumps(rows[-1][0]),))
    return count
