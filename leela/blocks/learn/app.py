import time
from pathlib import Path
from fastcore.basics import first
from fasthtml.common import FtResponse, JSONResponse, P
from ... import errstr
from ...core.web import NOT_OBJECT, fail, json_obj, off_loop
from ..memory.memory import _open_lock
from .ui import LookupPage, OpenedPage, Page, StepPage

__all__ = ['CAPS', 'connect']

CAPS = ('memory', 'search', 'docs', 'jobs', 'fs', 'fs_watch')

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

HEADERS = {'Content-Security-Policy': "frame-ancestors 'self'; img-src 'self' data:", 'Referrer-Policy': 'no-referrer'}
PANE_ONLY = 'The side pane shows only Learn pages.'

def read_step(memory, q):
    from abhyasa.store import Learning
    from .learn import find_step
    vault = memory._store('learning')
    with _open_lock(memory.path): return find_step(Learning(vault), q)

def said(req, root, text, code=200, title='Learn', pane=None, here=None):
    "A `learn` page of the one line `text`, with the status `code`; `pane` defaults to the query's `pane=1`."
    pane = req.query_params.get('pane') == '1' if pane is None else pane
    return FtResponse(Page(title, P(text, cls='lee-learn-line'), pane=pane, root=root, here=here), status_code=code, headers=HEADERS)

NO_INDEX = 'No code index yet.'

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

def os_why(e) -> str:
    "`e.strerror` and the name of the file in `e`, with no folder; empty when `e` has no `strerror`."
    return f'{e.strerror}: {Path(str(e.filename)).name}' if e.strerror and e.filename is not None else e.strerror or ''

def notebook_tab(docs, path):
    "The open notebook tab that `path` names, as given or resolved; None for no such tab."
    t = docs.tab_for(path) if path else None
    if path and t is None:
        try: t = docs.tab_for(str(Path(path).expanduser().resolve()))
        except (OSError, ValueError, RuntimeError): t = None
    return t if t is not None and t.kind == 'notebook' else None

def connect(app, ctx):
    def pane_only(req):
        "The one-line refusal for a `pane=1` request outside `/learn`; None for every other request."
        p = req.url.path
        if req.query_params.get('pane') == '1' and p != '/learn' and not p.startswith('/learn/'): return said(req, ctx.session.project_root, PANE_ONLY, 403)
    app.before.append(pane_only)
    @app.route('/lesson/due')
    async def lesson_due():
        try: return JSONResponse(await off_loop(due_cards, ctx.memory))
        except Exception as e: return fail(f'The learning vault is locked or unreadable. {errstr(e)}')
    @app.route('/learn', methods=['GET'])
    async def learn(req):
        from abhyasa.journey import read_handoff
        root = ctx.session.project_root
        try: q = read_handoff(req.url.query)
        except ValueError as e: return said(req, root, str(e), 400)
        try: v = await off_loop(read_step, ctx.memory, q)
        except ValueError as e: return said(req, root, str(e), 400)
        except Exception: return said(req, root, 'The learning store is locked or cannot be read.', 503)
        if v.kind == 'missing': return said(req, root, 'This walk is not in your learning store.')
        if v.kind == 'done': return said(req, root, 'This walk is done.')
        return FtResponse(StepPage(v, q, pane=req.query_params.get('pane') == '1', root=root), headers=HEADERS)
    @app.route('/learn/open', methods=['POST'])
    async def learn_open(req):
        from urllib.parse import urlencode
        from abhyasa.journey import handoff, read_handoff
        from ..fs.fs import Unsafe
        from .learn import Taken, open_step
        f, root = await req.form(), ctx.session.project_root
        say = lambda text, code=200: said(req, root, text, code, pane=f.get('pane') == '1')
        try: q = read_handoff(urlencode({k: f[k] for k in ('walk', 'step', 'topic') if f.get(k)}))
        except ValueError as e: return say(str(e), 400)
        try: v = await off_loop(read_step, ctx.memory, q)
        except ValueError as e: return say(str(e), 400)
        except Exception: return say('The learning store is locked or cannot be read.', 503)
        if v.kind == 'missing': return say('This walk is not in your learning store.')
        if v.kind == 'done': return say('This walk is done.')
        try: ctx.session.open_external(open_step(ctx.session, ctx.fs, v, q))
        except Taken as e: return say(str(e), 409)
        except ValueError as e: return say(str(e), 400)
        except Unsafe as e: return say(f'Leela could not write the lesson. {e}', 403)
        except OSError as e: return say(f'Leela could not write the lesson. {os_why(e)}'.strip(), 500)
        except Exception: return say('Leela could not open the lesson.', 500)
        # the pane keeps the step's own URL, so a reload does not GET this POST route
        return FtResponse(OpenedPage(v.j.title if v.kind == 'step' else v.name, handoff(q.walk, v.get('i', q.step), q.topic), pane=f.get('pane') == '1', root=root), headers=HEADERS)
    @app.route('/learn/lookup', methods=['GET'])
    async def learn_lookup(req):
        from .learn import pkg_names
        p = req.query_params
        q, path, given, root = p.get('q', '').strip(), p.get('path', ''), p.getlist('package'), ctx.session.project_root
        try: names = pkg_names(given)
        except ValueError as e: return said(req, root, str(e), 400, 'Look up code')
        try: rows = await off_loop(find_code, ctx.search, q, names, p.get('tool')) if q else []
        except Exception: rows = None
        t = notebook_tab(ctx.docs, path)
        return FtResponse(LookupPage(q, rows or [], given, ctx.docs.key(t) if t is not None else '', pane=p.get('pane') == '1', root=root,
                                     say=NO_INDEX if rows is None else None, tool=p.get('tool', '')), headers=HEADERS)
    @app.route('/learn/scratch', methods=['POST'])
    async def learn_scratch(req):
        from ..nb.nb import Notebook
        from .learn import scratch_cell
        if (d := await json_obj(req)) is None: return fail(NOT_OBJECT)
        path, snippet = d.get('path'), d.get('snippet')
        if not (path and isinstance(path, str) and isinstance(snippet, str)): return fail('Give the path of an open notebook and the snippet.')
        tab, live, _ = ctx.docs.owner(path)
        if live is None or not tab.path: return fail('That notebook is not open.')
        # as an agent's notebook edit: the file changes, and the open tab follows the disk
        nb = Notebook.load(tab.path)
        scratch_cell(nb, snippet)
        nb.save(tab.path, sandbox=ctx.fs)
        ctx.fs_watch.changed([tab.path])
        return {'ok': True, 'cells': [c.dict() for c in nb.cells], 'version': nb.version, 'index': len(nb.cells) - 1}
    @app.route('/learn/tool', methods=['POST'])
    async def learn_tool_make(req):
        from . import tools
        try: d = await req.json()
        except ValueError: d = None
        try: names = tools.tool_names(d.get('names') if isinstance(d, dict) else None)
        except ValueError as e: return fail(str(e))
        key = tools.tool_key(names)
        if tools.tool_python(key) and tools.tool_indexed(key): return {'ok': True, 'key': key, 'ready': True}
        if not tools.tool_python(key) and not tools.shutil.which('uv'): return fail(tools.NO_UV, 503)
        # no await between the check and the start, so one event loop starts one job for a key
        return {'ok': True, 'key': key, 'job': tools.start_tool_job(ctx.jobs, names).dict()}
    @app.route('/learn/tool', methods=['GET'])
    async def learn_tool(req):
        from .tools import tool_dir, tool_python
        key = req.query_params.get('key', '')
        try: tool_dir(key)
        except ValueError as e: return fail(str(e))
        p = tool_python(key)
        return {'ok': True, 'ready': p is not None, 'python': str(p) if p else None}
