"""Single bounded loopback HTTP owner behind the existing Tailscale HTTPS proxy."""
import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import signal
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from ops.cloud.monitoring_guard import monitoring_service
from reporting.agent_secretary import SecretaryArchive
from reporting.gate_web import dispatch


def main():
    os.umask(0o077);root=Path.home()/'.local/state/openclaw'
    private=Path.home()/'.config/openclaw/telegram.json'
    if private.stat().st_mode&0o077:raise PermissionError('Private Telegram config required')
    config=json.loads(private.read_text());policy=json.loads((root/'runtime/secretary-policy.json').read_text())
    if policy.get('approved') is not True or policy.get('grants_trading_permission') is not False:
        raise PermissionError('Approved secretary policy required')
    archive=SecretaryArchive(root/'agent_secretary.sqlite3')
    page=(Path(__file__).resolve().parents[2]/'web/secretary-limits/index.html').read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup();self.connection.settimeout(5)
        def log_message(self,*_):pass  # Never log auth payload, query strings or financial data.
        def reply(self,status,data,kind='application/json'):
            self.send_response(status);self.send_header('Content-Type',kind+'; charset=utf-8')
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline' https://telegram.org; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors https://web.telegram.org https://*.telegram.org")
            self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def do_GET(self):
            if self.path in ('/','/index.html'):self.reply(200,page,'text/html')
            else:self.reply(404,b'{}')
        def do_POST(self):
            try:
                if self.headers.get('Origin') not in (None,policy.get('limits_web_url','').rstrip('/')):
                    raise PermissionError('Origin mismatch')
                n=int(self.headers.get('Content-Length','0'))
                if not 0<n<=16000 or self.headers.get('Transfer-Encoding'):raise ValueError('Bounded request required')
                def unique(pairs):
                    d=dict(pairs)
                    if len(d)!=len(pairs):raise ValueError('Duplicate JSON field')
                    return d
                def invalid(_):raise ValueError('Nonfinite JSON')
                body=json.loads(self.rfile.read(n),object_pairs_hook=unique,parse_constant=invalid)
                result=dispatch(archive,root,config,policy,self.path,body)
                self.reply(200,json.dumps(result,ensure_ascii=False,allow_nan=False).encode())
            except (PermissionError,ValueError,KeyError,TypeError) as exc:
                self.reply(403 if isinstance(exc,PermissionError) else 400,json.dumps({'error':str(exc)[:160]},ensure_ascii=False).encode())
            except Exception:
                self.reply(503,b'{"error":"Temporary unavailable; do not blindly retry confirmation"}')

    stopped=False
    def stop(*_):
        nonlocal stopped
        stopped=True
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,stop)
    with monitoring_service('secretary-limits-web',root),HTTPServer(('127.0.0.1',8792),Handler) as server:
        from reporting.recovery import RecoveryCoordinator
        coordinator=RecoveryCoordinator(root/'runtime/recovery.sqlite3');sampled=0
        server.timeout=.5
        while not stopped:
            if time.monotonic()-sampled>=60:
                coordinator.observe('SECRETARY_LIMITS','HEALTHY',freshness='FRESH',enabled=True,
                    reason='Single loopback form owner bound; public HTTPS and Telegram clicks require separate acceptance')
                sampled=time.monotonic()
            server.handle_request()


if __name__=='__main__':main()
