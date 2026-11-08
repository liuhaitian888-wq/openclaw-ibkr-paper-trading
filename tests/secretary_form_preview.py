"""Bounded, loopback-only browser fixture. Fictitious data; confirmation is disabled."""
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
import json
import signal
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reporting.telegram_gate import DEFAULT,validate_form,GateValidationError


def main():
    repo=Path(__file__).resolve().parents[1]
    if not (repo/'.git').is_file():raise RuntimeError('Browser fixture belongs in a linked worktree')
    folder=repo/'web/secretary-limits';counts={'current':0,'preview':0,'confirm':0}
    class Handler(BaseHTTPRequestHandler):
        def setup(self):super().setup();self.connection.settimeout(3)
        def log_message(self,*_):pass
        def reply(self,status,data,kind='application/json'):
            if isinstance(data,dict):data=json.dumps(data,ensure_ascii=False).encode()
            self.send_response(status);self.send_header('Content-Type',kind+'; charset=utf-8');self.send_header('Cache-Control','no-store')
            self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def do_GET(self):
            if self.path in ('/','/server-error'):
                mode='offline-server-error' if self.path=='/server-error' else 'offline-preview'
                page=(folder/'index.html').read_text().replace('<script src="https://telegram.org/js/telegram-web-app.js"></script>',
                    '<script>window.Telegram={WebApp:{initData:'+json.dumps(mode)+',ready(){},expand(){}}};</script>')
                page=page.replace('<body>','<body><p style="background:#5a3d00;padding:12px">离线界面测试 · 全部为虚构数据 · 确认应用已禁用</p>')
                self.reply(200,page.encode(),'text/html')
            elif self.path=='/validation.js':self.reply(200,(folder/'validation.js').read_bytes(),'text/javascript')
            elif self.path=='/fixture-state':self.reply(200,counts)
            else:self.reply(404,{})
        def do_POST(self):
            n=int(self.headers.get('Content-Length','0'))
            if not 0<n<=16000:self.reply(400,{});return
            body=json.loads(self.rfile.read(n))
            if body.get('initData') not in ('offline-preview','offline-server-error'):self.reply(403,{});return
            if self.path=='/api/current':
                counts['current']+=1;self.reply(200,dict(revision=7,settings=DEFAULT))
            elif self.path=='/api/preview':
                counts['preview']+=1
                try:settings=validate_form(body['settings'])
                except GateValidationError as exc:self.reply(400,dict(error=str(exc),field_errors=exc.field_errors));return
                if body['initData']=='offline-server-error':
                    self.reply(400,dict(error='模拟服务器字段拒绝',field_errors={'max_risk_per_order':'模拟服务器拒绝：请检查单笔风险金额（USD）。'}));return
                self.reply(200,dict(id='fixture-no-authority',revision=7,settings=settings,previous=DEFAULT,expires=time.time()+600))
            elif self.path=='/api/confirm':counts['confirm']+=1;self.reply(409,dict(error='离线夹具禁止确认应用'))
            else:self.reply(404,{})
    stopped=False
    def stop(*_):
        nonlocal stopped
        stopped=True
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,stop)
    deadline=time.monotonic()+900
    with HTTPServer(('127.0.0.1',8766),Handler) as server:
        server.timeout=.5;print('Bounded fictitious-data fixture: http://127.0.0.1:8766/',flush=True)
        while not stopped and time.monotonic()<deadline:server.handle_request()


if __name__=='__main__':main()
