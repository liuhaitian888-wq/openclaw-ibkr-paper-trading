"""Single report dispatch entry. No snapshot refresh or trading-state mutation."""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.report_delivery_guard import STATE_DIR, expire_warnings
from scripts.send_daily_visual_feishu_update import send_daily_visual_update, REPORT_DIR

BJ = ZoneInfo('Asia/Shanghai')


def readiness(path, now):
    """Read only: no old-report catch-up, no refreshing financial data."""
    if not path.is_file(): return {'ready': False, 'reason': 'report_missing'}
    try:
        report = json.loads(path.read_text())
        trading_date = datetime.fromisoformat(report['trading_date']).date()
    except (ValueError, KeyError, TypeError):
        return {'ready': False, 'reason': 'invalid_report'}
    # Delivery may only consume a locally generated report from this dispatch date.
    generated_day = datetime.fromtimestamp(path.stat().st_mtime, BJ).date()
    if generated_day != now.astimezone(BJ).date():
        return {'ready': False, 'reason': 'report_not_generated_today'}
    if trading_date > now.astimezone(BJ).date():
        return {'ready': False, 'reason': 'future_trading_date'}
    return {'ready': True, 'trading_date': trading_date.isoformat()}


def run(now=None, report_path=REPORT_DIR/'latest.json', state_dir=STATE_DIR, sender=send_daily_visual_update):
    now = now or datetime.now(BJ)
    if now.tzinfo is None: raise ValueError('Timezone-aware datetime required')
    now = now.astimezone(BJ)
    if (state_dir/'PAUSED').exists(): return {'status':'PAUSED'}
    start = now.replace(hour=9,minute=0,second=0,microsecond=0)
    if not start <= now <= start+timedelta(hours=1,minutes=1):
        if now > start+timedelta(hours=1,minutes=1):expire_warnings(now,state_dir)
        return {'status':'OUTSIDE_WINDOW'}
    ready=readiness(report_path,now)
    if not ready['ready']:
        # Per-day local incident only. This code cannot dispatch a warning.
        state_dir.mkdir(parents=True,exist_ok=True)
        p=state_dir/('readiness-'+now.date().isoformat()+'.json')
        if not p.exists():
            # Exclusive creation prevents duplicate incident files from overlapping callers.
            try:
                with p.open('x') as f:json.dump({'status':'BLOCKED','reason':ready['reason'],'observed_at':now.isoformat(),'warning_id':'readiness:'+now.date().isoformat(),'local_only':True},f)
            except FileExistsError:pass
        return {'status':'NOT_READY',**ready}
    return sender(report_path=report_path)


if __name__ == '__main__':
    from trading.production_guard import production_service
    with production_service("sender"):
        print(json.dumps(run(),ensure_ascii=False))
