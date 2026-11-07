"""Read saved evidence and prepare financial reports; no network or sender."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ops.cloud.monitoring_guard import monitoring_service
from reporting.financial_reports import prepare_reports
from scripts.send_feishu_report import load_env_file, upload_image
import subprocess
import signal
import tempfile


def chrome_owned(arguments, *, capture=False):
    with tempfile.TemporaryDirectory(prefix='financial-render-') as profile:
        process=subprocess.Popen(['/usr/bin/google-chrome','--headless','--disable-gpu','--disable-background-networking','--disable-sync','--no-first-run',
                    '--user-data-dir='+profile,'--hide-scrollbars',*arguments],
                   stdout=subprocess.PIPE if capture else subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        try:
            output,_=process.communicate(timeout=15)
            if process.returncode:raise RuntimeError('Report rendering failed')
            return output.decode('utf-8') if capture else None
        finally:
            try:os.killpg(process.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            if process.poll() is None:
                try:process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=3)


def require_cjk_font():
    result=subprocess.run(['fc-match','-f','%{family}','Noto Sans CJK SC'],capture_output=True,text=True,timeout=3,check=True)
    if 'Noto Sans CJK' not in result.stdout:raise RuntimeError('Verified CJK font missing; refuse unreadable report')


def publish_image(html_path, png_path, *, upload=True):
    require_cjk_font()
    import re
    with tempfile.TemporaryDirectory(prefix='financial-measure-') as temporary:
        measure=Path(temporary)/'measure.html'
        script="<script>document.fonts.ready.then(()=>document.documentElement.setAttribute('data-render-height',Math.ceil(document.querySelector('main.page').getBoundingClientRect().height)+12))</script>"
        measure.write_text(html_path.read_text().replace('</body>',script+'</body>'))
        dom=chrome_owned(['--dump-dom','--virtual-time-budget=2000','--window-size=1200,1600',measure.resolve().as_uri()],capture=True)
    match=re.search(r'data-render-height="([0-9]+)"',dom)
    if not match or not 1600<=int(match[1])<=4000:raise RuntimeError('Report height could not be verified; refuse clipping')
    chrome_owned(['--window-size=1200,'+match[1],'--screenshot='+str(png_path),'--virtual-time-budget=1000',html_path.resolve().as_uri()])
    return upload_image(png_path) if upload else None


def main():
    os.umask(0o077)
    root=Path.home()/'.local/state/openclaw'
    if not (root/'runtime/FINANCIAL_REPORTS_ARMED').is_file():
        return 0
    expected=json.loads((Path.home()/'.config/openclaw/paper-observer.json').read_text())['expected_account']
    smtp = ((root/'runtime/BREVO_ALERTS_ARMED').is_file()
            or (root/'runtime/EMAIL_ALERTS_ARMED').is_file()
            or (root/'runtime/TELEGRAM_REPORTS_ARMED').is_file()
            or (root/'runtime/TELEGRAM_ALERTS_ARMED').is_file())
    credentials=Path.home()/'.config/openclaw/feishu-images.env'
    if not smtp and (not credentials.is_file() or credentials.stat().st_mode & 0o077):
        raise PermissionError('Private image-upload credentials required')
    if not smtp:
        load_env_file(credentials)
    with monitoring_service('financial-report-builder', root):
        print(json.dumps(prepare_reports(root,expected,datetime.now(timezone.utc),publish_image=lambda html,png: publish_image(html,png,upload=not smtp), transport="smtp" if smtp else "feishu")))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
