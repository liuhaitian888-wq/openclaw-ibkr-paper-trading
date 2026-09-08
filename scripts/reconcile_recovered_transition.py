"""Verify a recovered transition against healthy state history; write a supplement only.

Never modifies audit/source databases. A verified supplement is not a production
schema or a declaration that all damaged data was recovered.
"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def readonly(path):
    path = Path(path).resolve()
    # Only immutable, stopped snapshots. A WAL would invalidate this assumption.
    if any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm')):
        raise ValueError('Use a consolidated immutable snapshot without WAL/SHM')
    return sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)


def reconcile(recovered, healthy, transition_id, output):
    recovered, healthy, output = map(lambda x: Path(x).resolve(), (recovered, healthy, output))
    if output in (recovered, healthy):
        raise ValueError('Supplement cannot replace a source')
    source_hashes = {str(p): digest(p) for p in (recovered, healthy)}
    with closing(readonly(recovered)) as source, closing(readonly(healthy)) as state:
        source.row_factory = sqlite3.Row
        matches = [dict(r) for r in source.execute(
            'SELECT * FROM canonical_pool_transition_events WHERE transition_id=?', (transition_id,))]
        if len(matches) != 1:
            raise ValueError('Recovery occurrence is missing or non-unique')
        row = matches[0]
        payload = json.loads(row['payload_json'])
        if any(row.get(k) != v for k, v in payload.items()) or set(row) != set(payload) | {'payload_json'}:
            raise ValueError('Recovered columns and payload disagree')
        candidates = []
        for symbol, raw in state.execute('SELECT symbol,payload_json FROM canonical_pool_state WHERE symbol=?', (row['symbol'],)):
            for event in json.loads(raw).get('transition_history', []):
                if event.get('transition_id') == transition_id:
                    candidates.append((symbol, raw, event))
        if not candidates or any(event != payload for _, _, event in candidates):
            raise ValueError('Independent history missing or conflicting; preserve quarantine')
        evidence = {'sources': source_hashes, 'transition_id': transition_id,
                    'history_sha256': sorted({hashlib.sha256(raw.encode()).hexdigest() for _, raw, _ in candidates}),
                    'rule': 'exact full payload and all transition columns, no fuzzy matching',
                    'status': 'VERIFIED_RECOVERY', 'completeness': 'UNKNOWN'}
    if any(digest(p) != h for p, h in source_hashes.items()):
        raise ValueError('Source changed during verification')
    original = canonical(row)
    fp = hashlib.sha256(original.encode()).hexdigest()
    proof = canonical(evidence)
    if output.exists():
        with closing(readonly(output)) as out:
            actual = out.execute('SELECT fingerprint,original_json,evidence_json FROM verified_recovery').fetchall()
            if actual != [(fp, original, proof)]:
                raise ValueError('Existing supplement differs; refusing overwrite')
        return {'inserted': 0, 'verified': 1, 'fingerprint': fp}
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents clobbering another analyst's artifact.
    with output.open('xb'):
        pass
    with closing(sqlite3.connect(output)) as out, out:
        out.execute('CREATE TABLE verified_recovery (fingerprint TEXT PRIMARY KEY, original_json TEXT NOT NULL, evidence_json TEXT NOT NULL)')
        out.execute('INSERT INTO verified_recovery VALUES (?,?,?)', (fp, original, proof))
    return {'inserted': 1, 'verified': 1, 'fingerprint': fp}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('recovered', 'healthy', 'transition-id', 'output'):
        p.add_argument('--' + name, required=True)
    a = p.parse_args()
    print(json.dumps(reconcile(a.recovered, a.healthy, a.transition_id, a.output)))
