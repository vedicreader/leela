import asyncio, logging, time
from pathlib import Path
from fastcore.basics import first
from fasthtml.common import FtResponse, JSONResponse, P, RedirectResponse
from ... import errstr
from ...core.web import NOT_OBJECT, fail, json_obj, off_loop
from ..memory.memory import _open_lock
from ..settings.settings import register_section
from .speech import connect as connect_speech, speech_rows
from .ui import DocPage, FolderPage, LookupPage, OpenedPage, Page, StepPage

__all__ = ['CAPS', 'connect', 'learn_rows']

CAPS = ('memory', 'search', 'docs', 'jobs', 'fs', 'fs_watch')

log = logging.getLogger(__name__)

LEARN_GROUPS = ('walks', 'talks', 'checks', 'review', 'links', 'research', 'guide', 'lists')

def learn_rows():
    "The Learn settings section from Abhyasa's `SETTINGS`: file-stored rows of its own groups. Profile rows belong to the vault, and `sources.roots` to Leela's folder controls."
    try:
        from abhyasa.learner import SETTINGS, GROUPS
        return speech_rows() + [dict(key=r.name, dflt=r.dflt, kind=r.kind, lo=r.lo, hi=None if isinstance(r.hi, str) else r.hi, hi_key=r.hi if isinstance(r.hi, str) else None, choices=r.choices,
                     label=r.label, help=r.help, unit=r.unit, pct=r.pct, more=r.more, group=r.group, group_label=GROUPS[r.group][0])
                for r in SETTINGS.values() if r.group in LEARN_GROUPS and r.ui and r.store == 'file' and r.section != 'sources']
    except (ImportError, AttributeError, KeyError) as e:
        log.warning('Learn settings unavailable: %s', type(e).__name__)
        return []

def due_cards(memory):
    from abhyasa.learner import Learning
    from abhyasa.learner import recall, understanding
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

HEADERS = {'Content-Security-Policy': "frame-ancestors 'self'; img-src 'self' data:", 'Referrer-Policy': 'same-origin'}
PANE_ONLY = 'The side pane shows only Learn pages.'

def read_step(memory, q):
    from abhyasa.learner import Learning
    from .learn import find_step
    vault = memory._store('learning')
    with _open_lock(memory.path): return find_step(Learning(vault), q)

def read_doc(memory, q):
    from abhyasa.learner import Learning
    from .learn import doc_notebook
    vault = memory._store('learning')
    with _open_lock(memory.path): return doc_notebook(Learning(vault), q)

def go_now(req, q) -> bool:
    "Whether the link `q` opens its notebook at once: it asks to (`go`), and the browser does not mark it as from another site. A link from another site gets the page with the button."
    return q.go and req.headers.get('sec-fetch-site', '').lower() != 'cross-site'

def at_cell(q) -> str:
    "The IDE, at the cell `q.cell` of the notebook that opened."
    return '/' if q.cell is None else f'/?cell={q.cell}'

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

SWEEP = 10.   # seconds between two looks at the result of each open lesson

def connect(app, ctx):
    from .walk import connect as connect_walk; connect_walk(app, ctx)
    connect_speech(app, ctx)
    from .mode import LEARN
    from .tools import contract_missing, missing_line, register_learn_jobs
    register_learn_jobs(ctx.session)
    if missing := contract_missing(): log.warning('Learn is off: %s', missing_line(missing))
    elif rows := learn_rows(): register_section('learn', rows, 'abhyasa')
    filed = {}   # lesson path -> the `result_sig` last filed, or found filed already
    async def file_one(path):
        "File the result beside the lesson at `path` once for each write; a failure is said, and the next look tries again."
        from ..nb.lesson import file_result, result_sig
        if (sig := result_sig(path)) is None or filed.get(str(path)) == sig: return
        try: await off_loop(file_result, ctx.memory, path)
        except Exception as e: return print(f'  run result not filed: {errstr(e)}')
        filed[str(path)] = sig
    def lessons():
        "The notebook paths of the open tabs."
        return [t.path for t in ctx.docs.session.tabs if t.kind == 'notebook' and t.path]
    async def file_results():
        q, last = ctx.fs_watch.subscribe(), time.monotonic()
        try:
            while True:
                try: item = await asyncio.wait_for(q.get(), SWEEP)
                except TimeoutError: item = None
                paths = [item] if isinstance(item, str) else []   # a tab another process opened
                if isinstance(item, tuple) and len(item) == 2:
                    paths = [Path(p).parent.with_suffix('.ipynb') for p in map(Path, item[0]) if p.name == 'result.json' and p.parent.suffix == '.result']
                # the safety net, every SWEEP s and after a batch too big to name its paths: an event the watcher lost, a result written before Leela ran, or a failed try
                if item is None or (isinstance(item, tuple) and item[1:] == (True,)) or time.monotonic() - last >= SWEEP: paths, last = paths + lessons(), time.monotonic()
                for p in dict.fromkeys(map(str, paths)): await file_one(p)
        finally: ctx.fs_watch.unsubscribe(q)
    watching = []
    async def start_watching(): watching.append(asyncio.create_task(file_results()))
    async def stop_watching():
        for t in watching: t.cancel()
    app.on_event('startup')(start_watching)
    app.on_event('shutdown')(stop_watching)
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
        from abhyasa.contract import read_handoff
        from .learn import not_found, other_vault
        root = ctx.session.project_root
        try: q = read_handoff(req.url.query)
        except ValueError as e: return said(req, root, str(e), 400)
        if t := other_vault(q, ctx.memory.path): return said(req, root, t)
        pane = req.query_params.get('pane') == '1'
        if q.doc:
            if go_now(req, q) and not pane: return await open_now(req, q, None, root)
            try: nb = await off_loop(read_doc, ctx.memory, q)
            except ValueError as e: return said(req, root, str(e), 404)
            except Exception: return said(req, root, 'The learning store is locked or cannot be read.', 503)
            return FtResponse(DocPage(nb, q, pane=pane, root=root), headers=HEADERS)
        try: v = await off_loop(read_step, ctx.memory, q)
        except ValueError as e: return said(req, root, str(e), 400)
        except Exception: return said(req, root, 'The learning store is locked or cannot be read.', 503)
        if v.kind == 'missing': return said(req, root, not_found(q, ctx.memory.path))
        if v.kind == 'done': return said(req, root, 'This walk is done.')
        if go_now(req, q) and not pane: return await open_now(req, q, v, root)
        return FtResponse(StepPage(v, q, pane=req.query_params.get('pane') == '1', root=root, jobs=ctx.jobs), headers=HEADERS)
    @app.route('/learn/open', methods=['POST'])
    async def learn_open(req):
        f, root = await req.form(), ctx.session.project_root
        say = lambda text, code=200: said(req, root, text, code, pane=f.get('pane') == '1')
        try: q, v = await posted_step(f)
        except ValueError as e: return say(str(e), 400)
        except Exception: return say('The learning store is locked or cannot be read.', 503)
        return await open_now(req, q, v, root, f.get('pane') == '1')
    async def open_now(req, q, v, root, pane=False):
        "Open the lesson of the `find_step` result `v`, or abhyasa's learning copy of its notebook, or the vault notebook `q.doc`; then the IDE at the cell `q.cell`, or the opened page in the pane. Adds no folder: one the file needs is offered beside a loose tab, or asked for on a 409 page in a folder window."
        from abhyasa.contract import handoff
        from ..fs.fs import Unsafe
        from ...core.projects import loose_root
        from ...hub import declined
        from .learn import Taken, not_found, open_step, project_root
        say = lambda text, code=200: said(req, root, text, code, pane=pane)
        what = 'open the notebook' if q.doc else 'write the lesson'
        if isinstance(v, str): return say(v)
        if v is not None and v.kind == 'missing': return say(not_found(q, ctx.memory.path))
        if v is not None and v.kind == 'done': return say('This walk is done.')
        try:
            if q.doc: path, need = project_root(ctx.session, ctx.fs, await off_loop(read_doc, ctx.memory, q))
            else: path, need = open_step(ctx.session, ctx.fs, v, q)
            if need and ctx.fs.loose is None and ctx.fs.roots: return FtResponse(FolderPage(path.name, path, need, pane=pane, root=root), status_code=409, headers=HEADERS)
            if need and ctx.fs.loose is None: ctx.session.add_root(loose_root(), loose=True)
            t = ctx.session.open_external(opened := path)
            if need and not declined(need[0]): ctx.session.offers[t.path], ctx.session.offer_also[t.path] = str(need[0]), [str(a) for a in need[1:]]
        except Taken as e: return say(str(e), 409)
        except ValueError as e: return say(str(e), 400)
        except Unsafe as e: return say(f'Leela could not {what}. {e}', 403)
        except OSError as e: return say(f'Leela could not {what}. {os_why(e)}'.strip(), 500)
        except Exception: return say('Leela could not open the lesson.', 500)
        if not q.doc: await file_one(opened)   # a result written before this lesson opened
        # in a tab of its own the learner goes to the IDE, where the lesson is now the active tab
        if not pane: return RedirectResponse(at_cell(q), 303)
        # the pane keeps the step's own URL, so a reload does not GET this POST route
        if q.doc: return FtResponse(OpenedPage(opened.name, '', pane=True, root=root), headers=HEADERS)
        return FtResponse(OpenedPage(v.j.title if v.kind == 'step' else v.name, handoff(q.walk, v.get('i', q.step), q.topic, v=q.v), pane=True, root=root), headers=HEADERS)
    async def posted_step(f):
        "The handoff in the form `f` and its `find_step` result, or the one line for another vault in place of the result. `ValueError` for a bad form."
        from urllib.parse import urlencode
        from abhyasa.contract import read_handoff
        from .learn import other_vault
        q = read_handoff(urlencode({k: f[k] for k in ('walk', 'step', 'topic', 'doc', 'shelf', 'cell', 'v') if f.get(k)}))
        if t := other_vault(q, ctx.memory.path): return q, t
        return q, None if q.doc and not q.walk else await off_loop(read_step, ctx.memory, q)
    @app.route('/learn/env', methods=['POST'])
    async def learn_env(req):
        from . import tools
        from .learn import not_found
        f, root = await req.form(), ctx.session.project_root
        say = lambda text, code=200: said(req, root, text, code, pane=f.get('pane') == '1')
        try: q, v = await posted_step(f)
        except ValueError as e: return say(str(e), 400)
        except Exception: return say('The learning store is locked or cannot be read.', 503)
        if isinstance(v, str): return say(v)
        if v is None: return say('This step needs no packages.', 400)
        if v.kind == 'missing': return say(not_found(q, ctx.memory.path))
        if v.kind != 'step' or not (names := (v.nb or {}).get('requires')): return say('This step needs no packages.', 400)
        from abhyasa.contract import handoff
        back = RedirectResponse(handoff(q.walk, v.i, v=q.v) + ('&pane=1' if f.get('pane') == '1' else ''), 303)
        if (st := tools.env_state(ctx.jobs, tools.tool_key(names))) in ('ready', 'indexing'): return back
        if st == 'missing' and not tools.shutil.which('uv'): return say(tools.NO_UV, 503)
        tools.start_tool_job(ctx.jobs, names)   # no await since the check: one event loop starts one job for a key
        return back
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
        if tools.tool_kernel(key) and tools.tool_indexed(key): return {'ok': True, 'key': key, 'ready': True}
        if not tools.tool_kernel(key) and not tools.shutil.which('uv'): return fail(tools.NO_UV, 503)
        # no await between the check and the start, so one event loop starts one job for a key
        return {'ok': True, 'key': key, 'job': tools.start_tool_job(ctx.jobs, names).dict()}
    @app.route('/learn/tool', methods=['GET'])
    async def learn_tool(req):
        from .tools import env_job, env_state, tool_dir, tool_indexed, tool_kernel
        from .ui import env_say
        key = req.query_params.get('key', '')
        try: tool_dir(key)
        except ValueError as e: return fail(str(e))
        p = tool_kernel(key)
        st = env_state(ctx.jobs, key)
        return {'ok': True, 'ready': p is not None, 'python': str(p) if p else None, 'indexed': tool_indexed(key), 'state': st, 'say': env_say(st, env_job(ctx.jobs, key))}
