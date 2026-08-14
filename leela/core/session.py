"State one application session owns: open docs, running cells, the debugger, the journal."

from __future__ import annotations
import asyncio
from fastcore.basics import first
import json, time, uuid
from pathlib import Path

__all__ = ['DocStore', 'DebugState', 'RunState', 'kernel_api']

async def kernel_api(session, path, params=None, timeout=15, tab=None):
    "Proxy an inspector call through the exact runtime `Run` would use."
    client = await session.runtime(tab)
    return await client.api(path, params, timeout) if client else None

class DocStore:
    "Open notebooks and unsaved file text, keyed by tab."
    __slots__ = ('session', 'docs', 'buffers', 'bases', 'run_locks')
    def __init__(self, session):
        self.session = session
        self.docs = {}
        self.buffers = {}
        self.bases = {}
        self.run_locks = {}
    @staticmethod
    def key(tab): return None if tab is None else (tab.path or tab.title)
    def current(self):
        "The notebook behind the active tab, or None when the active tab is not one."
        return self.docs.get(self.key(self.session.tab)) if self.session.tab else None
    def tab_for(self, ref):
        "The tab a request names, falling back to the active one. Survives a tab switch mid-flight."
        ref = str(ref or '')
        if not ref: return self.session.tab
        return first(t for t in self.session.tabs if self.key(t) == ref)
    def owner(self, ref):
        "`(tab, notebook, run_lock)` for a notebook request, or `(None, None, None)`."
        tab = self.tab_for(ref)
        if tab is None or tab.kind != 'notebook': return None, None, None
        lock = self.run_locks.setdefault(self.session.kernel_key(tab), asyncio.Lock())
        return tab, self.docs.get(self.key(tab)), lock
    def mark_all_stale(self):
        "A reset namespace makes every saved output historical, even though it stays useful."
        for nb in self.docs.values():
            for c in nb.cells: c.fresh = False
    def forget(self, key):
        "Drop everything held for one tab. Safe to call for a key that was never opened."
        for d in (self.docs, self.buffers, self.bases): d.pop(key, None)

class DebugState:
    "Which kernel is paused, and where the frame it stopped in came from."
    __slots__ = ('kernel', 'origin_path', 'cell_id', 'direct_session', 'direct_task', 'direct_name')
    def __init__(self):
        self.kernel = None
        self.origin_path = ''
        self.cell_id = ''
        self.direct_session = None
        self.direct_task = None
        self.direct_name = ''
    @property
    def paused(self): return self.kernel is not None
    def clear(self):
        self.kernel, self.origin_path, self.cell_id = None, '', ''
    def clear_direct(self):
        self.direct_session, self.direct_task, self.direct_name = None, None, ''
    @property
    def cell_sources(self):
        "Temporary debug source path -> cell id, as recorded by the kernel that is paused."
        return getattr(self.kernel, '_debug_sources', {}) or {}

class RunState:
    "In-flight cell executions, so Stop stays aimed at the cell that started the work."
    __slots__ = ('cells',)
    def __init__(self): self.cells = {}
    def start(self, tab_key, cell_id, runtime, task): self.cells[(tab_key, cell_id)] = (runtime, task)
    def get(self, tab_key, cell_id): return self.cells.get((tab_key, cell_id), (None, None))
    def finish(self, tab_key, cell_id): return self.cells.pop((tab_key, cell_id), None)
    def running_in(self, tab_key):
        "Cell ids currently executing in one tab."
        return [cid for (tk, cid) in self.cells if tk == tab_key]

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
        op = (first(x for x in reversed(self.operations) if x['id'] == operation_id) if operation_id else
              first(x for x in self.operations if x.get('resources') and x.get('undone') and x.get('redoable', True)))
        if op is None: raise ValueError('no redoable workspace operation')
        if not op.get('undone'): raise ValueError('that operation was not undone')
        conflicts = [str(self.sandbox._check(row['path'])) for row in op['resources']
                     if self._current(row['path']) != row['before']]
        if conflicts: raise ValueError('changed after the undo: ' + ', '.join(conflicts))
        for row in op['resources']: self._write(row['path'], row['after'])
        op['undone'] = False; self._save(); return op
