"The state `ide_app` keeps in its closure, made into objects blocks can share."

from __future__ import annotations

import asyncio

from fastcore.basics import first

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
