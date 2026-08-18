"Live variables, proxied from each kernel's own dhrishti inspector."

from __future__ import annotations

from fasthtml.common import JSONResponse

from ...core.session import kernel_api
from ...core.web import fail
from ..runtime.kernels import KernelLimit

__all__ = ['CAPS', 'connect']

CAPS = ()

def _api_path(name, scope):
    "`live` asks the tab's kernel; `agent` asks its overlay, which mounts the same names."
    return f'/agent/api/{name}' if scope == 'agent' else f'/api/{name}'

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
        try: runtime = await session.runtime()
        except KernelLimit as e: return fail(e)
        r = await runtime.api(_api_path('rows', scope), {'profile': profile, 'sort': sort}, 15) if runtime else None
        identity = ((getattr(runtime, 'base', None) or
                     (f'kernel:{session.kernel_key()}' if runtime is not None else 'none')) + f':{scope}')
        problem = (getattr(runtime, 'boot_error', '') or getattr(runtime, 'last_api_error', '') or
                   'no dhrishti inspector') if not r else ''
        return {**(r or {'groups': [], 'error': problem}), 'runtime': identity,
                'inspector': 'dhrishti', 'python': str(getattr(runtime, 'python', '') or ''),
                'cwd': str(getattr(runtime, 'cwd', '') or '')}
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
    @rt('/vars/promote')
    async def vars_promote(accessor: str):
        r = await api('/api/promote', {'accessor': accessor})
        return r or {'ok': False, 'error': 'no kernel inspector'}
