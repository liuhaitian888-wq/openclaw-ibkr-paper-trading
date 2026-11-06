"""Send generic opt-in heartbeats. No account, position or log payload leaves host."""
from datetime import datetime, timezone
from contextlib import closing
import sqlite3
import time
import json
from pathlib import Path
import re
import ssl
from urllib.request import build_opener, HTTPSHandler, HTTPRedirectHandler, Request


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fresh(observation, now):
    try:
        age = (now-datetime.fromisoformat(observation['observed_at'])).total_seconds()
        return 0 <= age <= 600
    except (KeyError, TypeError, ValueError):
        return False



def heartbeat_attempt(root, name, healthy, send):
    """Persist an attempt before wire and its native HTTP confirmation afterwards."""
    path=root/'recovery.sqlite3'
    started=time.time()
    with closing(sqlite3.connect(path,timeout=5)) as c,c:
        c.execute('CREATE TABLE IF NOT EXISTS heartbeat_delivery(id INTEGER PRIMARY KEY,check_name TEXT,healthy INTEGER,started REAL,ack REAL,http_status INTEGER,outcome TEXT)')
        ident=c.execute('INSERT INTO heartbeat_delivery(check_name,healthy,started,outcome) VALUES(?,?,?,?)',
                        (name,int(healthy),started,'STARTED')).lastrowid
    status=None;ack=None;outcome='UNKNOWN'
    try:
        status=send()
        if status==200:ack=time.time();outcome='HTTP_ACCEPTED'
        else:outcome='HTTP_REJECTED'
    except Exception:
        # May have reached the provider; no fabricated ACK or automatic replay.
        pass
    with closing(sqlite3.connect(path,timeout=5)) as c,c:
        c.execute('UPDATE heartbeat_delivery SET ack=?,http_status=?,outcome=? WHERE id=?',(ack,status,outcome,ident))
    return outcome=='HTTP_ACCEPTED'


def main():
    config_path = Path.home()/'.config/openclaw/healthchecks.json'
    if not config_path.is_file():
        print('EXTERNAL_MONITOR_NOT_CONFIGURED')
        return 0
    if config_path.stat().st_mode & 0o077:
        raise PermissionError('Heartbeat config must be mode 0600')
    cfg = json.loads(config_path.read_text())
    urls = {key:cfg[key] for key in ('host_url','paper_api_url')}
    for url in urls.values():
        if not isinstance(url,str) or not re.fullmatch(r'https://hc-ping\.com/[a-fA-F0-9-]{36}',url):
            raise ValueError('Use official hc-ping.com UUID URLs only')
    root = Path.home()/'.local/state/openclaw/runtime'
    def read(name):
        try: return json.loads((root/name).read_text())
        except (OSError, ValueError): return {}
    host = read('cloud-status.json'); paper = read('paper-observer.latest.json')
    expected_path=Path.home()/'.config/openclaw/paper-observer.json'
    expected=json.loads(expected_path.read_text())['expected_account']
    now=datetime.now(timezone.utc)
    host_ok=fresh(host,now) and host.get('disk_free_fraction',0)>=.20
    paper_ok=(fresh(paper,now) and paper.get('complete') is True
              and paper.get('environment')=='PAPER' and paper.get('account_id')==expected
              and paper.get('resources',{}).get('connected_after_close') is False)
    opener=build_opener(HTTPSHandler(context=ssl.create_default_context()),NoRedirect())
    failures=0
    for name,ok in (('host_url',host_ok),('paper_api_url',paper_ok)):
        endpoint=urls[name]+('' if ok else '/fail')
        def send():
            with opener.open(Request(endpoint,method='GET'),timeout=8) as response:
                return response.status
        if not heartbeat_attempt(root,name,ok,send):
            print(name+': heartbeat unconfirmed'); failures+=1
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
