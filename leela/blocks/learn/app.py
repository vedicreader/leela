import time
from fastcore.basics import first
from fasthtml.common import FtResponse, JSONResponse
from starlette.responses import PlainTextResponse
from ... import errstr
from ...core.web import fail, off_loop
from ..memory.memory import _open_lock
from .ui import LookupPage, StepPage

__all__ = ['CAPS', 'connect']

CAPS = ('memory', 'search', 'docs', 'jobs')

def due_cards(memory):
    from abhyasa.store import Learning
    from abhyasa.model import recall, understanding
    vault = memory._store('learning')
    with _open_lock(memory.path):
        lr, now = Learning(vault), time.time()
        due = [c for c in lr.concepts() if c.seen and c.due and c.due <= now]
        rows = []
        for c in sorted(due, key=lambda c: c.due):
            a = first(lr.attempts(c.slug, limit=1)) or {}
            rows.append(dict(name=c.name, slug=c.slug, **{k: a.get(k, '') for k in ('question', 'answer', 'thinking', 'actual')},
                why=f'due for review: recall about {recall(c, now):.0%}', reason=first(understanding(c, now).reasons) or ''))
        return rows

HEADERS = {'Content-Security-Policy': "frame-ancestors 'self'", 'Referrer-Policy': 'no-referrer'}

def read_step(memory, q):
    from abhyasa.store import Learning
    from .learn import find_step
    vault = memory._store('learning')
    with _open_lock(memory.path): return find_step(Learning(vault), q)

def said(text, code=200): return PlainTextResponse(text, status_code=code, headers=HEADERS)

NO_INDEX = 'No code index for this yet.'

def kosha_for(search, tool=None):
    "The kosha handle of the tool environment `tool` when it is ready; else the project handle."
    from .tools import tool_dir, tool_python
    if tool_python(tool) is None: return search._kosha()
    import kosha
    return kosha.Kosha(dir=tool_dir(tool))

def find_code(search, q, names, tool=None):
    "The `lookup` rows for `q` in `names`, or None when there is no code index."
    from .learn import lookup
    k = kosha_for(search, tool)
    if k is None or not k.pkgs2consider(): return None
    return lookup(k, q, names)

def connect(app, ctx):
    @app.route('/lesson/due')
    async def lesson_due():
        try: return JSONResponse(await off_loop(due_cards, ctx.memory))
        except Exception as e: return fail(f'The learning vault is locked or unreadable. {errstr(e)}')
    @app.route('/learn', methods=['GET'])
    async def learn(req):
        from abhyasa.journey import read_handoff
        try: q = read_handoff(req.url.query)
        except ValueError as e: return said(str(e), 400)
        try: v = await off_loop(read_step, ctx.memory, q)
        except ValueError as e: return said(str(e), 400)
        except Exception: return said('The learning store is locked or cannot be read.', 503)
        if v.kind == 'missing': return said('This walk is not in your learning store.')
        if v.kind == 'done': return said('This walk is done.')
        return FtResponse(StepPage(v, q, pane=req.query_params.get('pane') == '1'), headers=HEADERS)
    @app.route('/learn/lookup', methods=['GET'])
    async def learn_lookup(req):
        from .learn import pkg_names
        p = req.query_params
        q, path, given = p.get('q', '').strip(), p.get('path', ''), p.getlist('package')
        try: names = pkg_names(given)
        except ValueError as e: return said(str(e), 400)
        try: rows = await off_loop(find_code, ctx.search, q, names, p.get('tool')) if q else []
        except Exception: rows = None
        if rows is None: return said(NO_INDEX)
        t = ctx.docs.tab_for(path) if path else None
        return FtResponse(LookupPage(q, rows, given, path if t is not None and t.kind == 'notebook' else '', pane=p.get('pane') == '1'), headers=HEADERS)
    @app.route('/learn/scratch', methods=['POST'])
    async def learn_scratch(req):
        from .learn import scratch_cell
        d = await req.json()
        path, snippet = d.get('path'), d.get('snippet')
        if not (path and isinstance(path, str) and isinstance(snippet, str)): return fail('Give the path of an open notebook and the snippet.')
        tab, nb, _ = ctx.docs.owner(path)
        if nb is None: return fail('That notebook is not open.')
        scratch_cell(nb, snippet)
        tab.dirty = True
        return {'ok': True, 'cells': [c.dict() for c in nb.cells], 'version': nb.version, 'index': len(nb.cells) - 1}
    @app.route('/learn/tool', methods=['POST'])
    async def learn_tool_make(req):
        from . import tools
        try: d = await req.json()
        except ValueError: d = None
        try: names = tools.tool_names(d.get('names') if isinstance(d, dict) else None)
        except ValueError as e: return fail(str(e))
        key = tools.tool_key(names)
        if tools.tool_python(key): return {'ok': True, 'key': key, 'ready': True}
        if not tools.shutil.which('uv'): return fail(tools.NO_UV, 503)
        # no await between the check and the start, so one event loop starts one job for a key
        job = tools.active_job(ctx.jobs, key) or ctx.jobs.start('tool_env', key, names=names)
        return {'ok': True, 'key': key, 'job': job.dict()}
    @app.route('/learn/tool', methods=['GET'])
    async def learn_tool(req):
        from .tools import tool_dir, tool_python
        key = req.query_params.get('key', '')
        try: tool_dir(key)
        except ValueError as e: return fail(str(e))
        p = tool_python(key)
        return {'ok': True, 'ready': p is not None, 'python': str(p) if p else None}
