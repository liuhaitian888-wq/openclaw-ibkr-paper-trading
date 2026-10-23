"""Send generic opt-in heartbeats. No account, position or log payload leaves host."""
from datetime import datetime, timezone
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
        try:
            with opener.open(Request(endpoint,method='GET'),timeout=8) as response:
                if response.status!=200: raise RuntimeError('Ping not accepted')
        except Exception:
            print(name+': heartbeat failed'); failures+=1
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
