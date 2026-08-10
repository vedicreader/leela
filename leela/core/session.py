"""The state `ide_app` keeps in its closure, made into objects blocks can share.

`Workspace` is not the only coupling in `leela/app.py`. The 2,594-line `ide_app`
closure also holds mutable state of its own -- open notebook documents, unsaved buffers,
per-kernel run locks, the paused debugger -- and route groups that look unrelated reach
into it. `/tab/state`, `/nb/save`, `/tabs/save-all`, `/tab/buffer`, `/tab/reload` and
`/history/undo` all touch `_docs`; `_debug` is read by sixteen places.

That is a harder problem than `ws.*` for extraction, because a closure variable cannot be
imported. Moving `/nb/save` into a block while `_docs` stays in `app.py` does not compile,
and moving `_docs` with it strands `/tab/state`. So the state becomes objects first, owned
by the session and reached as capabilities, and the routes move afterwards.

Nothing here is new behaviour. Each class is the closure state it replaces, with the
helpers that already operated on it (`_doc`, `_run_owner`, `_previous_runs`) attached to
the data they were always about.
"""

from __future__ import annotations

import asyncio

__all__ = ['DocStore', 'DebugState', 'RunState', 'kernel_api']


async def kernel_api(session, path, params=None, timeout=15, tab=None):
    """Proxy an inspector call through the exact runtime `Run` would use.

    Deliberately resolves `Workspace.runtime` rather than independently peeking at an
    inspector. A selected venv may restart or replace the tab's kernel, and execution and
    Variables have to cross the same runtime boundary on every request -- not merely happen
    to agree while the old kernel is still cached.

    Proxying at all is what keeps the page single-origin: each kernel hosts its own
    dhrishti inspector on its own port, so letting the browser reach those directly would
    mean CORS on every kernel and the owner token living in the browser.
    """
    client = await session.runtime(tab)
    return await client.api(path, params, timeout) if client else None


class DocStore:
    """Open notebooks and unsaved file text, keyed by tab.

    The server holds the document rather than the browser, which is what keeps structural
    edits and runs consistent across a page reload. Keys are `tab.path or tab.title`, so an
    untitled scratch notebook is addressable before it has ever been saved.
    """

    __slots__ = ('session', 'docs', 'buffers', 'bases', 'run_locks')

    def __init__(self, session):
        self.session = session
        self.docs = {}          # tab key -> Notebook
        self.buffers = {}       # tab key -> unsaved text, surviving tab switches
        self.bases = {}         # tab key -> the disk version a browser draft began from
        # Admission happens before kernel startup. `Kernel.execute` serialises live
        # requests, but two first cells can both wait on the same startup and then reach
        # that lock in the opposite order -- definitions and their tests have to execute in
        # submission order, so the lock is taken here, per kernel.
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
        return next((t for t in self.session.tabs if self.key(t) == ref), None)

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
    """Which kernel is paused, and where the frame it stopped in came from.

    A paused debugger belongs to the kernel that started it, not to whichever tab happens
    to be active while stepping through another source file -- hence `origin_path` and
    `cell_id`, which map a temporary cell source back to the notebook that submitted it.
    `direct` is the separate script-debugging session, which has no notebook behind it.
    """

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
    """In-flight cell executions, so Stop stays aimed at the cell that started the work.

    Keyed by `(tab key, cell id)` rather than by tab: switching tabs before pressing Stop
    must not retarget it, and two notebooks can be running at once.
    """

    __slots__ = ('cells',)

    def __init__(self): self.cells = {}

    def start(self, tab_key, cell_id, runtime, task): self.cells[(tab_key, cell_id)] = (runtime, task)
    def get(self, tab_key, cell_id): return self.cells.get((tab_key, cell_id), (None, None))
    def finish(self, tab_key, cell_id): return self.cells.pop((tab_key, cell_id), None)

    def running_in(self, tab_key):
        "Cell ids currently executing in one tab."
        return [cid for (tk, cid) in self.cells if tk == tab_key]
