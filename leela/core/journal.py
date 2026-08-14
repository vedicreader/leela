"""Persistent workspace operation history; undo is refused unless every resource still
equals the operation's recorded `after` value."""
from __future__ import annotations
import json, time, uuid
from pathlib import Path
from fastcore.basics import first

MAX_OPERATIONS = 200


class OperationJournal:
    "The last `MAX_OPERATIONS` workspace operations, on disk, newest last."

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
        "Append one operation, or None when nothing actually changed."
        rows = [{'path': str(path), 'before': before, 'after': after}
                for path, before, after in resources if before != after]
        if not rows and not irreversible: return None
        # A new edit starts a new history branch; earlier undone edits are no longer redoable.
        for prior in self.operations:
            if prior.get('undone'): prior['redoable'] = False
        op = {'id': 'op_' + uuid.uuid4().hex[:12], 'at': time.time(), 'label': str(label),
              'kind': kind, 'resources': rows, 'irreversible': list(irreversible), 'undone': False}
        self.operations.append(op); self.operations = self.operations[-MAX_OPERATIONS:]; self._save()
        return op

    def rows(self, limit=50):
        "The newest `limit` operations, without their `before`/`after` bodies."
        return [{k: v for k, v in op.items() if k != 'resources'} |
                {'paths': [r['path'] for r in op.get('resources', [])],
                 'reversible': bool(op.get('resources')) and not op.get('undone'),
                 'redoable': bool(op.get('resources')) and op.get('undone') and op.get('redoable', True)}
                for op in reversed(self.operations[-int(limit):])]

    def _current(self, path):
        "One resource as it is on disk right now, or None when it is not there."
        p = self.sandbox._check(path)
        return p.read_text(encoding='utf-8', errors='replace') if p.exists() else None

    def _write(self, path, text):
        p = self.sandbox._check(path)
        if text is None:
            if p.exists(): p.unlink()
        else: self.sandbox.write(p, text)

    def undo(self, operation_id=''):
        "Reverse one operation, named or the newest reversible one."
        back = reversed(self.operations)
        op = (first(x for x in back if x['id'] == operation_id) if operation_id else
              first(x for x in back if x.get('resources') and not x.get('undone')))
        if op is None: raise ValueError('no reversible workspace operation')
        if op.get('undone'): raise ValueError('that operation was already undone')
        conflicts = [str(self.sandbox._check(row['path'])) for row in op['resources']
                     if self._current(row['path']) != row['after']]
        if conflicts: raise ValueError('changed after the operation: ' + ', '.join(conflicts))
        for row in op['resources']: self._write(row['path'], row['before'])
        op['undone'] = True; self._save(); return op

    def redo(self, operation_id=''):
        "Reapply one undone operation when every file still equals its restored text."
        # Undo peels newest-first, so redo must reapply oldest-first: after undoing two edits to
        # one file, redoing the newer one would find the file at the older one's `before` text
        # and refuse. Only the unnamed pick scans forwards; an id names exactly one operation.
        op = (first(x for x in reversed(self.operations) if x['id'] == operation_id) if operation_id else
              first(x for x in self.operations if x.get('resources') and x.get('undone') and x.get('redoable', True)))
        if op is None: raise ValueError('no redoable workspace operation')
        if not op.get('undone'): raise ValueError('that operation was not undone')
        conflicts = [str(self.sandbox._check(row['path'])) for row in op['resources']
                     if self._current(row['path']) != row['before']]
        if conflicts: raise ValueError('changed after the undo: ' + ', '.join(conflicts))
        for row in op['resources']: self._write(row['path'], row['after'])
        op['undone'] = False; self._save(); return op
