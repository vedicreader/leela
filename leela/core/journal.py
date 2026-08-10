"""Persistent, conflict-safe workspace operation history.

The journal stores text snapshots outside the repository. Undo is conditional: every
resource must still equal the operation's recorded ``after`` value, otherwise the whole
operation is refused before any file is touched.
"""
from __future__ import annotations
import json, time, uuid
from pathlib import Path

MAX_OPERATIONS = 200


class OperationJournal:
    def __init__(self, path, sandbox):
        self.path, self.sandbox = Path(path), sandbox
        self.operations = []
        self._load()

    def _load(self):
        try: self.operations = json.loads(self.path.read_text()).get('operations', [])[-MAX_OPERATIONS:]
        except Exception: self.operations = []

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps({'operations': self.operations[-MAX_OPERATIONS:]}, ensure_ascii=False))
        tmp.replace(self.path)

    def record(self, label, resources, kind='file', irreversible=()):
        rows = []
        for path, before, after in resources:
            if before == after: continue
            rows.append({'path': str(path), 'before': before, 'after': after})
        if not rows and not irreversible: return None
        op = {'id': 'op_' + uuid.uuid4().hex[:12], 'at': time.time(), 'label': str(label),
              'kind': kind, 'resources': rows, 'irreversible': list(irreversible), 'undone': False}
        self.operations.append(op); self.operations = self.operations[-MAX_OPERATIONS:]; self._save()
        return op

    def rows(self, limit=50):
        return [{k: v for k, v in op.items() if k != 'resources'} |
                {'paths': [r['path'] for r in op.get('resources', [])],
                 'reversible': bool(op.get('resources')) and not op.get('undone')}
                for op in reversed(self.operations[-int(limit):])]

    def undo(self, operation_id=''):
        op = next((x for x in reversed(self.operations) if x['id'] == operation_id), None) if operation_id else \
             next((x for x in reversed(self.operations) if x.get('resources') and not x.get('undone')), None)
        if op is None: raise ValueError('no reversible workspace operation')
        if op.get('undone'): raise ValueError('that operation was already undone')
        conflicts = []
        for row in op['resources']:
            p = self.sandbox._check(row['path'])
            current = p.read_text(encoding='utf-8', errors='replace') if p.exists() else None
            if current != row['after']: conflicts.append(str(p))
        if conflicts: raise ValueError('changed after the operation: ' + ', '.join(conflicts))
        for row in op['resources']:
            p = self.sandbox._check(row['path'])
            if row['before'] is None:
                if p.exists(): p.unlink()
            else:
                self.sandbox.write(p, row['before'])
        op['undone'] = True; self._save(); return op
