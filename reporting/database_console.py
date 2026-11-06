"""Bounded read-only database inventory. Never repairs, checks or writes live DBs."""
from contextlib import closing
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import sqlite3
import time


DATABASES = (
    ('trading_audit.sqlite3', '交易审计', '券商回调、持仓、订单、成交和历史审计',
     (('paper_readback_observations', 'observed_at'), ('executions', 'first_seen_at'))),
    ('financial_ledger.sqlite3', '财务账本', '财务事实、导入与核对记录',
     (('observations', 'inserted_at'),)),
    ('runtime/recovery.sqlite3', '监控与通知', '故障、恢复、心跳、通知队列与回执',
     (('paper_callback_events', 'observed'), ('runtime_health_samples', 'observed'))),
    ('agent_secretary.sqlite3', 'Agent 秘书档案', '用户指示、分析摘要、工具、策略与回测档案',
     (('secretary_events', 'recorded_at'),)),
)


def contained(root, relative):
    root = Path(root).absolute()
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts or root.is_symlink():
        raise ValueError('Contained state path required')
    target = root
    for part in relative.parts:
        target = target / part
        if target.is_symlink():
            raise ValueError('Symlink refused')
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError('Path outside state root')
    return target


def stamp(value, now):
    try:
        if isinstance(value, (float, int)):
            dt = datetime.fromtimestamp(value, timezone.utc)
        else:
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if dt.tzinfo is None or not 0 <= now - dt.timestamp():
            return None
        return dt.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, AttributeError, OverflowError, OSError):
        return None


def backup_inventory(root, now):
    """Manifests are records, not permission to read arbitrary paths or claim PASS."""
    results = {}
    folder = contained(root, 'backups')
    if not folder.is_dir():
        return results
    candidates = sorted(folder.glob('*/backup.json'), reverse=True)[:256]
    for candidate in candidates:
        try:
            p = contained(root, candidate.relative_to(root))
            if p.stat().st_size > 1_000_000:
                continue
            data = json.loads(p.read_text())
            if not isinstance(data, dict) or not isinstance(data.get('items'), list):
                continue
            created = datetime.strptime(data['created_at'], '%Y%m%dT%H%M%S.%fZ').replace(tzinfo=timezone.utc)
            if created.timestamp() > now:
                continue
            for item in data['items']:
                if not isinstance(item, dict):
                    continue
                source = item.get('source')
                if source not in {r[0] for r in DATABASES} or source in results:
                    continue
                filename = item.get('file', '')
                if not filename or Path(filename).name != filename:
                    continue
                packed = contained(root, candidate.parent.relative_to(root) / filename)
                exists = packed.is_file()
                results[source] = dict(at=created.isoformat(), status=item.get('status'),
                    age_seconds=now-created.timestamp(), file_present=exists,
                    recorded_sha256=bool(isinstance(item.get('sha256_uncompressed'), str)
                        and len(item['sha256_uncompressed']) == 64),
                    checksum_verified=False, integrity='NOT_INDEPENDENTLY_VERIFIED',
                    evidence='备份任务记录；本页面未解压、重算哈希或检查完整性')
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return results


def inspect_database(root, definition, *, now, query_budget=.1):
    relative, name, purpose, probes = definition
    out = dict(path=relative, name=name, purpose=purpose, state='UNKNOWN',
               live_integrity='NOT_CHECKED', last_business_at=None,
               last_business_scope='声明表中的时间戳，不证明全库最后提交时间', probes=[])
    try:
        p = contained(root, relative)
        if not p.is_file():
            out['state'] = 'NOT_CREATED'
            return out
        out.update(state='PRESENT', bytes=p.stat().st_size)
        stats = [(relative, p.stat())]
        for suffix in ('-wal', '-shm'):
            sidecar = contained(root, relative + suffix)
            if sidecar.is_file():
                st = sidecar.stat()
                out[suffix[1:]+'_bytes'] = st.st_size
                if suffix == '-wal':
                    stats.append((relative+suffix, st))
        out['file_changed_at'] = datetime.fromtimestamp(max(s.st_mtime for _, s in stats), timezone.utc).isoformat()
        out['file_changed_scope'] = 'DB/WAL文件mtime；不是精确写入或提交时间'
        # mode=ro must not create a missing database; do not use immutable on WAL.
        with closing(sqlite3.connect(p.as_uri()+'?mode=ro', uri=True, timeout=.1)) as c:
            c.execute('PRAGMA query_only=ON')
            deadline = time.monotonic() + query_budget
            c.set_progress_handler(lambda: int(time.monotonic() > deadline), 500)
            out['journal_mode'] = c.execute('PRAGMA journal_mode').fetchone()[0]
            out['table_count'] = c.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
            for table, column in probes:
                deadline = time.monotonic() + query_budget
                try:
                    value = c.execute(f'SELECT max("{column}") FROM "{table}"').fetchone()[0]
                    at = stamp(value, now)
                    out['probes'].append(dict(table=table, column=column, at=at,
                                              state='OBSERVED' if at else 'UNKNOWN'))
                except sqlite3.Error as exc:
                    out['probes'].append(dict(table=table, column=column,
                        state='TIME_BUDGET_OR_LOCK' if 'interrupt' in str(exc).lower() or 'lock' in str(exc).lower() else 'UNAVAILABLE'))
            dates = [p['at'] for p in out['probes'] if p.get('at')]
            out['last_business_at'] = max(dates) if dates else None
            out['state'] = 'READABLE_METADATA'
    except (OSError, ValueError, sqlite3.Error):
        out['state'] = 'UNREADABLE_OR_REFUSED'
    return out


def collect(root, *, now=None, query_budget=.1):
    now = time.time() if now is None else now
    try:
        backups = backup_inventory(root, now)
    except (OSError, ValueError):
        backups = {}
    rows = [inspect_database(root, d, now=now, query_budget=query_budget) for d in DATABASES]
    for row in rows:
        row['backup'] = backups.get(row['path'])
    return dict(observed_at=datetime.fromtimestamp(now, timezone.utc).isoformat(),
                mode='READ_ONLY_SNAPSHOT', databases=rows,
                limitations=['快照非实时；重新运行采集器才更新',
                             '未扫描运行库完整性，未执行checkpoint/VACUUM/恢复',
                             '备份逐库一致，不保证跨库原子；异地备份尚未验证'])


def render(data):
    esc = lambda value: html.escape(str(value if value is not None else '未知'))
    rows = []
    for item in data['databases']:
        backup = item.get('backup') or {}
        size = f"{item['bytes']/1024/1024:,.2f} MiB" if 'bytes' in item else '尚未创建 / 未知'
        bstatus = '无备份记录'
        if backup:
            bstatus = ('任务成功' if backup.get('status') == 'BACKED_UP' else '任务未成功')
            bstatus += ' · 文件' + ('存在' if backup.get('file_present') else '缺失')
            if backup.get('age_seconds', 0) > 48*3600:
                bstatus += ' · 超过48小时'
        rows.append(f'''<tr><td><strong>{esc(item['name'])}</strong><code>{esc(item['path'])}</code>
          <small>{esc(item['purpose'])}</small></td><td>{size}<small>WAL {esc(item.get('wal_bytes',0))} bytes</small></td>
          <td><span class="badge">{esc(item['state'])}</span><small>{esc(item.get('journal_mode'))} · {esc(item.get('table_count'))} 张表</small></td>
          <td>{esc(item.get('last_business_at'))}<small>声明表中的业务时间</small><br>{esc(item.get('file_changed_at'))}<small>DB/WAL文件变动时间</small></td>
          <td>{esc(backup.get('at'))}<small>{esc(bstatus)}</small></td>
          <td><span class="warn">当前库：未执行完整性检查</span><small>备份哈希：{'已记录，未复算' if backup.get('recorded_sha256') else '未知'}<br>备份独立校验：未验证</small></td></tr>''')
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>数据库管理 · 只读状态</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#101721;color:#e7edf6;font:15px/1.65 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;padding:36px}
main{max-width:1600px;margin:auto}h1{font-size:30px;margin:8px 0}p,small{color:#a8b8cc}small,code{display:block}code{color:#9fcaed;font-size:12px;overflow-wrap:anywhere}
.intro{display:flex;justify-content:space-between;gap:24px;align-items:center}.badge{display:inline-block;padding:4px 9px;border-radius:8px;background:#203347;color:#b7d9f1;font-size:12px}.warn{color:#f6cb81}
.panel{background:#172230;border:1px solid #2d3e52;border-radius:16px;padding:20px;margin:24px 0}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;min-width:1100px}th{text-align:left;color:#9eafc4;font-weight:500;font-size:13px}td,th{padding:18px 14px;border-bottom:1px solid #29394d;vertical-align:top}td{font-size:13px}strong{font-size:16px}footer{margin-top:25px;font-size:13px;color:#a8b8cc}@media(max-width:700px){body{padding:16px}.intro{display:block}}
</style><main><div class="intro"><div><span class="badge">READ ONLY · 独立快照</span><h1>数据库管理</h1><p>库存、写入证据、备份与校验状态。此页面不提供修改、删除或恢复操作。</p></div><p>采集时间 UTC<br>''' + esc(data['observed_at']) + '''</p></div><section class="panel scroll"><table><thead><tr><th>数据库 / 用途</th><th>大小</th><th>元数据可读性</th><th>最近写入证据（UTC）</th><th>最近备份（UTC）</th><th>校验状态</th></tr></thead><tbody>''' + ''.join(rows) + '''</tbody></table></section><section class="panel"><strong>如何理解这些状态</strong><p>文件变动时间不等于精确最后提交时间；“可读”不等于完整性通过。备份任务成功不等于当前库已校验，已有哈希不等于已复算。</p><p>异地备份是把加密副本存到另一台机器或独立存储；当前未验证。页面为快照，刷新页面不会重新查询服务器。</p></section><footer>''' + '<br>'.join(esc(x) for x in data['limitations']) + '</footer></main></html>'
