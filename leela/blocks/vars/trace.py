"A traced run of one notebook cell: kept for the session, shown in the variables pane, and written as text for the agent."

from __future__ import annotations

import hashlib

__all__ = ['TracedKernel', 'TraceStore', 'trace_context', 'trace_store', 'trace_support']

KEEP = 24
ANCHOR_TRACE = 1500

def trace_support(k=None):
    "'' when this kunda and dhrishti can trace a run (and kernel `k`, if given), else one sentence for the person."
    try: import dhrishti.trace  # noqa: F401
    except ImportError: return 'needs a newer dhrishti'
    try: import kunda.trace  # noqa: F401
    except ImportError: return 'needs a newer kunda'
    if k is not None and not hasattr(k, 'run_traced'): return 'needs a newer kunda'
    return ''

class TracedKernel:
    "A kernel as `Notebook.run` sees it: `execute` runs the cell traced and keeps the events in `run`."
    def __init__(self, k, **kw): self.k, self.kw, self.run = k, kw, None
    async def execute(self, code, **kw):
        self.run = r = await self.k.run_traced(code, **self.kw, **kw)
        return r
    def __getattr__(self, name): return getattr(self.k, name)

def _sig(src): return hashlib.sha1((src or '').encode()).hexdigest()[:12]

class TraceStore:
    "The last two traced runs of each cell in this session, by tab and cell id."
    def __init__(self): self.runs = {}
    def put(self, key, events, source, info=None):
        "Keep `events`; the run before it becomes `prev`. Returns the model the pane draws."
        old = self.runs.pop(key, None)
        self.runs[key] = dict(events=events, source=source, sig=_sig(source), info=info or {}, prev=old['events'] if old else None)
        while len(self.runs) > KEEP: self.runs.pop(next(iter(self.runs)))
        return self.model(key)
    def get(self, key): return self.runs.get(key)
    def model(self, key):
        "The table, states and series of a kept run, with `was` marks against the run before it."
        from dhrishti.trace import trace_model
        r = self.runs.get(key)
        if r is None: return None
        return {**trace_model(r['events'], prev=r['prev']), 'source': r['source'], 'has_prev': r['prev'] is not None, **r['info']}

def trace_store(ws):
    "The session's `TraceStore`, made on first use."
    s = getattr(ws, 'traces', None)
    if s is None: s = ws.traces = TraceStore()
    return s

def trace_context(ws, tab, cell):
    "The cell's trace as compact text for the agent, or '' unless the person traced this cell in this session and has not edited it since."
    s = getattr(ws, 'traces', None)
    r = s.get((getattr(tab, 'path', None) or getattr(tab, 'title', ''), cell.id)) if s else None
    if r is None or r['sig'] != _sig(cell.source): return ''
    try: from dhrishti.trace import trace_text
    except ImportError: return ''
    return trace_text(r['events'], r['source'], max_chars=ANCHOR_TRACE)
