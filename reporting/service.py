"""Shared report application service. Trigger adapters only supply event and clock."""
import json
from pathlib import Path
from zoneinfo import ZoneInfo
from .generation import generate
from .recovery import recover

def run(trigger,root,output,now,*,delivery=None,kind=None,collector=None,renderer=None,simulation=False,approved_hash=None):
    if trigger not in ('manual','scheduler','recovery'):raise ValueError('Invalid trigger')
    if kind is None:
        from scripts.report_aggregation import select_type
        kind=select_type(now.astimezone(ZoneInfo('Asia/Shanghai')).date(),'first_day')
    # No scheduler-specific math, generation or send implementation.
    folder=Path(output)/now.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()/kind.lower()
    saved=folder/'manifest.json'
    if delivery and saved.exists():manifest=json.loads(saved.read_text())
    else:manifest=generate(root,kind,now,folder,trigger=trigger,collector=collector,renderer=renderer,simulation=simulation)
    if delivery is None:return {'status':'LOCAL_PREVIEW','manifest':manifest}
    # Candidate only: Delivery keeps production paused and requires sandbox transport.
    return delivery.attempt(manifest,now,approved_hash=approved_hash,trigger=trigger)
