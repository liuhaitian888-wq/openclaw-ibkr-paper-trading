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


def publish_image(html_path, png_path, *, upload=True):
    with tempfile.TemporaryDirectory(prefix='financial-render-') as profile:
        process=subprocess.Popen(['/usr/bin/google-chrome','--headless','--disable-gpu','--disable-background-networking','--disable-sync','--no-first-run',
                    '--user-data-dir='+profile,
                    '--no-pdf-header-footer','--hide-scrollbars','--window-size=1200,2200',
                    '--screenshot='+str(png_path),html_path.resolve().as_uri()],
                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        try:
            if process.wait(timeout=15):
                raise RuntimeError('Report rendering failed')
        finally:
            try:
                os.killpg(process.pid,signal.SIGTERM)
            except ProcessLookupError:
                pass
            if process.poll() is None:
                try:process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL)
                    process.wait(timeout=3)
    return upload_image(png_path) if upload else None


def main():
    os.umask(0o077)
    root=Path.home()/'.local/state/openclaw'
    if not (root/'runtime/FINANCIAL_REPORTS_ARMED').is_file():
        return 0
    expected=json.loads((Path.home()/'.config/openclaw/paper-observer.json').read_text())['expected_account']
    smtp = ((root/'runtime/BREVO_ALERTS_ARMED').is_file()
            or (root/'runtime/EMAIL_ALERTS_ARMED').is_file())
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
