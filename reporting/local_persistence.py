"""Shared negative persistence gate. Absence of a fault is never readiness."""
from contextlib import closing
from pathlib import Path
import json,sqlite3,time

MARKER_NAME='paper-local-persistence-fault.json'


def has_local_persistence_fault(root,connection=None,*,marker_only=False):
    """Read only; a supplied SQLite connection remains caller-owned."""
    root=Path(root).resolve();marker=root/'runtime'/MARKER_NAME
    try:
        if marker.exists() or marker.is_symlink():return True
        if marker_only:return False
        if connection is None:
            database=root/'runtime/recovery.sqlite3'
            if database.is_symlink() or database.parent.is_symlink():return True
            with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True,timeout=.2)) as c:
                c.execute('PRAGMA query_only=ON');deadline=time.monotonic()+.2
                c.set_progress_handler(lambda:int(time.monotonic()>deadline),500)
                return has_local_persistence_fault(root,c)
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='module_observations'").fetchone():return False
        row=connection.execute("SELECT payload FROM module_observations WHERE name='LOCAL_STATE'").fetchone()
        value=json.loads(row[0]) if row else {}
        if not isinstance(value,dict):return True
        return bool(value.get('local_persistence_failure')) or marker.exists() or marker.is_symlink()
    except (OSError,ValueError,TypeError,sqlite3.Error):return True
