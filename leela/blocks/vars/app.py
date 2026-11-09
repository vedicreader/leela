"Live variables, proxied from each kernel's own dhrishti inspector."

from __future__ import annotations

import json

from fasthtml.common import JSONResponse

from ...core.inspectors import import_failure
from ...core.session import kernel_api
from ...core.web import fail
from ..runtime.kernels import KernelLimit
from .trace import TracedKernel, trace_store, trace_support
from kunda.support import INSPECTOR, installable

__all__ = ['CAPS', 'connect']

CAPS = ('docs',)

def _api_path(name, scope):
    "`live` asks the tab's kernel; `agent` asks its overlay, which mounts the same names."
    return f'/agent/api/{name}' if scope == 'agent' else f'/api/{name}'

def _whole_name(accessor):
    "The top-level name an accessor names, or None. dhrishti promotes nothing else."
    try: a = json.loads(accessor)
    except Exception: return None
    if not (isinstance(a, list) and len(a) == 1 and isinstance(a[0], str)): return None
    return a[0] if a[0].isidentifier() else None

async def _replaces(api, name):
    "What promoting `name` would take from the user, as one sentence, or ''."
    info = await api('/agent/api/info')
    if info is not None and name not in set(info.get('agent_names') or ()): return ''
    rows = await api('/api/rows', {'profile': 'minimal', 'sort': 'name'})
    if rows is None:
        # an inspector that answered nothing at all is the one `/api/promote` reports for itself
        if info is None: return ''
        return (f'the live namespace could not be read, so promoting {name} can replace a value '
                'that is already there')
    if name not in {n.get('name') for g in rows.get('groups', []) for n in g.get('nodes', [])}: return ''
    return (f'{name} already exists in the live namespace. Promoting replaces it, and the value '
            'that is there now cannot be brought back.')

def connect(app, ctx):
    rt = app.route
    session = ctx.session
    async def api(path, params=None, timeout=15): return await kernel_api(session, path, params, timeout)
    @rt('/inspect')
    async def inspect_route(req):
        "Signature and docstring for the name at the cursor, from the object that is actually loaded."
        d = await req.json()
        try: k = await session.runtime()
        except KernelLimit as e: return fail(e)
        txt = await k.inspect_obj(d.get('code', ''), int(d.get('pos', 0)), int(d.get('detail', 0))) if k else ''
        return {'text': txt, 'note': '' if txt else 'the kernel knows nothing about that name'}
    @rt('/vars/eval')
    async def vars_eval(req):
        "Evaluate a Python expression from the Variables filter and return an expandable result."
        d = await req.json()
        code, scope = (d.get('code') or '').strip(), d.get('scope', 'live')
        if not code: return fail('enter a Python expression after =')
        try: k = await session.runtime()
        except KernelLimit as e: return fail(e)
        params = {'code': code, 'scope': 'overlay' if scope == 'agent' else 'global'}
        r = await k.api(_api_path('exec', scope), params, timeout=120) if k else None
        if r is None: return fail('no runtime answered')
        return {'ok': bool(r.get('ok')), 'error': r.get('error'), 'stdout': r.get('stdout') or '',
                'result': r.get('result'), 'scope': scope}
    @rt('/vars')
    async def vars_route(profile: str = 'minimal', sort: str = 'recent', scope: str = 'live'):
        "The live variables, or nothing where no kernel is running."
        runtime = session.kernel_peek()
        r = await runtime.api(_api_path('rows', scope), {'profile': profile, 'sort': sort}, 15) if runtime else None
        identity = ((getattr(runtime, 'base', None) or
                     (f'kernel:{session.kernel_key()}' if runtime is not None else 'none')) + f':{scope}')
        boot = getattr(runtime, 'boot_error', '') or ''
        problem = (boot or getattr(runtime, 'last_api_error', '') or 'no dhrishti inspector') if not r else ''
        py = str(getattr(runtime, 'python', '') or '')
        # Offered off the boot error alone. A failed inspector call is a live inspector that did not
        # answer once, and installing packages is no answer to that.
        can_install = bool(problem and import_failure(boot) and installable(py))
        return {**(r or {'groups': [], 'error': problem}), 'runtime': identity,
                'inspector': 'dhrishti', 'python': py,
                **({'can_install': True, 'packages': list(INSPECTOR)} if can_install else {}),
                'cwd': str(getattr(runtime, 'cwd', '') or '')}
    def trace_key(tab, c): return (tab.path or tab.title, c.id)
    @rt('/vars/trace/support')
    async def trace_caps():
        "Whether this install can trace a run, and the sentence to show when it cannot."
        why = trace_support(session.kernel_peek())
        return {'ok': not why, 'why': why}
    @rt('/vars/trace/last')
    async def trace_last(path: str = '', id: str = ''):
        "The last traced run of one cell in this session, as the pane draws it."
        tab, nb, _ = ctx.docs.owner(path)
        c = next((x for x in (nb or []) if x.id == id), None)
        m = trace_store(session).model(trace_key(tab, c)) if c is not None else None
        return {'ok': True, 'trace': m}
    @rt('/vars/trace')
    async def vars_trace(req):
        "Run one code cell with a line tracer on, as a normal run, and return its cell and its trace."
        d = await req.json()
        tab, nb, lock = ctx.docs.owner(d.get('path'))
        if nb is None: return fail('no notebook open')
        if (why := trace_support()): return fail(why, 409)
        c = next((x for x in nb if x.id == d.get('id')), None)
        if c is None: return fail('that cell is no longer in the notebook', 409)
        if c.cell_type != 'code': return fail('only code cells can be traced')
        if 'source' in d:
            row = {'id': c.id, 'i': nb.cells.index(c), 'source': d['source'], 'seq': d.get('seq')}
            if nb.take_sources([row], ctx.docs.seqs_for(tab)): return fail('another window changed this cell. Review it before tracing.', 409)
        from ..nb.nb import run_watched
        async with lock:
            try: k = await session.runtime(tab)
            except KernelLimit as e: return fail(e)
            if (why := trace_support(k)): return fail(why, 409)
            tk = TracedKernel(k)
            tab.running += 1
            try: c, lost = await run_watched(nb, c, tk)
            finally: tab.running = max(0, tab.running - 1)
        tab.dirty = True
        r = tk.run
        info = dict(truncated=bool(r and r.truncated), reason=r and r.reason, seen=r.seen if r else 0, secs=r.secs if r else 0)
        m = trace_store(session).put(trace_key(tab, c), r.events if r else [], c.source, info)
        return {'ok': not c.has_error, 'id': c.id, 'lost': lost, 'cell': c.dict(), 'trace': m}
    @rt('/vars/expand')
    async def vars_expand(accessor: str, offset: int = 0, scope: str = 'live'):
        return JSONResponse(await api(_api_path('expand', scope), {'accessor': accessor, 'offset': offset}) or [])
    @rt('/vars/grid')
    async def vars_grid(accessor: str, roff: int = 0, coff: int = 0, scope: str = 'live'):
        return JSONResponse(await api(_api_path('grid', scope), {'accessor': accessor, 'roff': roff, 'coff': coff}))
    @rt('/vars/set')
    async def vars_set(req):
        d = await req.json()
        r = await api('/api/set', {'accessor': d['accessor'], 'expr': d['expr']})
        return r or {'ok': False, 'error': 'no kernel inspector'}
    @rt('/vars/promote', methods=['POST'])
    async def vars_promote(accessor: str, replace: int = 0):
        "Hand one name the agent bound to the user; a name the user already has needs `replace`."
        name = _whole_name(accessor)
        try:
            if name and not replace:
                taken = await _replaces(api, name)
                if taken: return fail(taken, 409)
            r = await api('/api/promote', {'accessor': accessor})
            if r is None: return {'ok': False, 'error': 'no kernel inspector'}
            # a promoted name left in both layers falls outside the policy that refuses owner mutations
            if r.get('ok') and name: await api('/agent/api/exec', {'code': f'del {name}', 'scope': 'overlay'})
            return r
        except KernelLimit as e: return fail(e)
