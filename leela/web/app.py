"""The web IDE.

The server owns state and structure; the browser owns the editors. Anything
with a text cursor is CodeMirror talking JSON to these routes, and everything
else -- file tree, variable tree, tab bar, status -- is server-rendered htmx,
reusing the fragments leela already knows how to build.

Variable data is *proxied* rather than fetched cross-origin. Each kernel hosts
its own inspector on its own port; letting the page hit those ports directly
would mean CORS on every kernel and the owner token sitting in the browser.
Proxying keeps the token server-side and the page single-origin.

The exec strip's two scopes are genuinely different runtimes, not a flag:
`live` runs on the tab's kernel, sharing the notebook's namespace, while
`isolated` runs through the agent session's safepyrun sandbox, where writes are
discarded and escapes refused. (The older `scope='isolated'` copies the
namespace dict shallowly, so a mutating call still reached the real object --
routing the toggle at the sandbox makes the label true.)
"""

from __future__ import annotations
import asyncio, json, os
from urllib.parse import quote
from fasthtml.common import *          # re-exports fastcore's Path, L, first, asdict, ...
from starlette.routing import WebSocketRoute

from ..inspect.core import PROFILES, SORTS
from .. import errstr
from ..diffs import diff_label, diff_rows, did_you_mean, fuzzy_rank, udiff
from ..fs import lang_for
from ..keys import web_keymap, help_rows, toast_rows, by_scope
from ..nb import Notebook, Cell
from ..term import TerminalGate, lazygit_argv, LazygitMissing
from ..workspace import Workspace

__all__ = ['ide_app', 'serve_ide']


def static_dir(): return Path(__file__).parent/'static'


def _fail(err, code=400):
    "The IDE's JSON error shape. `err` is an exception (reported `Type: message`) or a ready string."
    return JSONResponse({'ok': False, 'error': errstr(err) if isinstance(err, Exception) else str(err)},
                        status_code=code)


def _found(ws, hits):
    "A hit list plus the backend that produced it -- an empty result is never a mystery."
    return {'backend': ws.search.backend, 'note': ws.search.note, 'hits': [h.dict() for h in hits]}


async def _off_loop(fn, *a, **kw):
    """Run a blocking call on a worker thread.

    Everything research and the model do is synchronous and slow -- a page fetch, a
    forward pass. Called directly from a route they would stall the event loop, which
    means the file tree stops responding while the agent thinks.
    """
    return await asyncio.to_thread(fn, *a, **kw)


def _diff(was, now):
    "One text-vs-text comparison in the shape every diff surface in the client consumes."
    return {'label': diff_label(was, now), 'rows': [r.dict() for r in diff_rows(udiff(was, now))]}


async def _explain(k, err, scope='live'):
    """A kernel error with a `did you mean` appended, when a near-miss name exists.

    Guarded on the message rather than run for every failure: the suggestion costs an
    extra call to the kernel's inspector, and only a `NameError` can use one.
    """
    if not (err and 'is not defined' in err): return err
    return did_you_mean(err, await k.names(scope)) if k else err


# ---------------------------------------------------------------------------
# chrome
# ---------------------------------------------------------------------------
def _tab_bar(ws):
    "The open tabs. `alt+1..9` selects, the x closes."
    if not ws.tabs: return Div(Span('no files open', cls='lee-dim'), id='tabbar', cls='lee-tabbar')
    kids = []
    for i, t in enumerate(ws.tabs):
        cls = 'lee-tab' + (' active' if i == ws.active else '') + (' dirty' if t.dirty else '')
        kids.append(Div(
            Span('●', cls='lee-dot') if t.dirty else '',
            Span(t.title, cls='lee-tab-name'),
            Span('×', cls='lee-tab-x', hx_post=f'/tab/close?i={i}', hx_target='#tabbar', hx_swap='outerHTML'),
            cls=cls, title=t.path or t.title,
            hx_post=f'/tab/select?i={i}', hx_target='#tabbar', hx_swap='outerHTML'))
    return Div(*kids, id='tabbar', cls='lee-tabbar')


def _kernel_pill(ws):
    "Kernel identity and liveness for the active tab."
    k = ws.kernel_peek()
    if k is None: return Span('no kernel', cls='lee-pill lee-pill-off', id='kpill')
    if not k.alive: return Span('kernel dead', cls='lee-pill lee-pill-err', id='kpill')
    nm = Path(ws.kernel_key()).name or 'kernel'
    return Span(f'⏺ {nm}', cls='lee-pill lee-pill-on', id='kpill',
                title=f'{k.base or "no inspector"} · pid {k.pid}')


def _header(ws):
    return Header(
        Span('leela', cls='lee-brand'),
        _tab_bar(ws),
        Span(cls='lee-spacer'),
        _kernel_pill(ws),
        Button('⟳', cls='lee-icon', title='restart kernel', onclick='leeAct("restart")'),
        Button('⏸', cls='lee-icon', title='interrupt kernel', onclick='leeAct("interrupt")'),
        Button('⌘', cls='lee-icon', title='command palette', onclick='leeAct("palette")'),
        cls='lee-header', id='header')


def _tree_node(e):
    "One file-tree row; directories lazily fetch their children on first open."
    if e.is_dir:
        return Details(
            Summary(Span('▸', cls='lee-caret'), Span(e.name, cls='lee-fname'),
                    hx_get=f'/tree?path={quote(e.path)}', hx_target='next .lee-kids', hx_trigger='click once'),
            Div(cls='lee-kids'),
            cls='lee-node lee-dir' + (' lee-root' if e.is_root else ''), data_path=e.path)
    return Div(Span(e.name, cls='lee-fname'),
               cls='lee-node lee-file', data_path=e.path, data_lang=e.lang or '',
               hx_post=f'/tab/open?path={quote(e.path)}', hx_target='#tabbar', hx_swap='outerHTML')


def _files_panel(ws):
    body = [_tree_node(e) for e in ws.fs.ls(None)] or [Div('no folder open', cls='lee-dim')]
    return Section(
        Div(Span('files', cls='lee-ptitle'),
            Button('+', cls='lee-icon', title='open folder', onclick='leeAct("add_root")'),
            cls='lee-phead'),
        Div(*body, id='filetree', cls='lee-tree'),
        cls='lee-panel lee-files')


def _toast_panel():
    "The left-sidebar cheatsheet: the keys that earn space but do not fit the footer."
    rows = [Div(Kbd(k), Span(lbl), cls='lee-krow') for k, lbl in toast_rows()]
    return Section(
        Div(Span('keys', cls='lee-ptitle'),
            Button('all', cls='lee-icon', title='every binding', onclick='leeAct("help")'),
            cls='lee-phead'),
        Div(*rows, cls='lee-toast'),
        cls='lee-panel lee-keys')


def _vars_panel(ws):
    """The right sidebar: live/isolated toggle, filter, then the variable tree.

    The toggle sits above the filter because it selects *which namespace* is being
    filtered -- it governs the exec strip and this tree together.
    """
    return Section(
        Div(Span('variables', cls='lee-ptitle'),
            Div(Button('live', id='sc-live', cls='lee-seg active', onclick='leeScope("live")'),
                Button('isolated', id='sc-iso', cls='lee-seg', onclick='leeScope("isolated")'),
                cls='lee-segbar', title='live runs in the kernel · isolated is sandboxed and discards writes'),
            cls='lee-phead'),
        Div(Input(id='varfilter', placeholder='filter…', cls='lee-input', oninput='leeFilterVars()'),
            Select(*[Option(p, value=p, selected=(p == 'minimal')) for p in PROFILES],
                   id='varprofile', cls='lee-select', onchange='leeVars()'),
            Select(*[Option(s, value=s, selected=(s == 'recent')) for s in SORTS],
                   id='varsort', cls='lee-select', onchange='leeVars()'),
            cls='lee-filterbar'),
        Div(Div('connect a kernel to see variables', cls='lee-dim'), id='vars', cls='lee-vars'),
        cls='lee-panel lee-varspanel')


def _editor_pane(ws):
    "The centre. Content is mounted by the client from /tab/state; this is the frame."
    t = ws.tab
    if t is None:
        return Div(Div('open a file, or press ', Kbd('ctrl+p'), cls='lee-empty'), id='editor', cls='lee-editor')
    return Div(id='editor', cls='lee-editor', data_kind=t.kind, data_path=t.path, data_lang=t.lang or '')


def _exec_strip():
    "The merged exec box. One editor; the live/isolated toggle above decides where it runs."
    return Section(
        Div(Span('exec', cls='lee-ptitle'), Span(id='execscope', cls='lee-scope-tag'),
            Span(cls='lee-spacer'),
            Button('clear', cls='lee-icon', onclick='leeExecClear()'),
            cls='lee-phead'),
        Div(id='execlog', cls='lee-execlog'),
        Div(id='execbox', cls='lee-execbox'),
        cls='lee-panel lee-exec')


def _term_panel(gate):
    """The terminal drawer: hidden until `ctrl+alt+~` asks for it.

    Rendered even when terminals are disabled, so the reason shows up in the place the
    user looked for the feature rather than as silence.
    """
    body = (Div(id='term', cls='lee-term')
            if gate.enabled else Div(gate.why, cls='lee-dim lee-termoff'))
    return Section(
        Div(Span('terminal', cls='lee-ptitle'), Span(id='termtag', cls='lee-scope-tag'),
            Span(cls='lee-spacer'),
            Button('lazygit', cls='lee-icon', title='git ops', onclick='leeAct("git")'),
            Button('×', cls='lee-icon', title='close terminal', onclick='leeAct("term_close")'),
            cls='lee-phead'),
        body,
        cls='lee-panel lee-termpanel', id='termwrap')


def _agent_panel():
    "Bottom centre: the agent session, with room reserved for the prompt bar that will drive leela."
    return Section(
        Div(Span('agent', cls='lee-ptitle'),
            Span(id='agentnames', cls='lee-dim'),
            Span(cls='lee-spacer'),
            Button('transcript', cls='lee-icon', onclick='leeAgentTranscript()'),
            cls='lee-phead'),
        Div(id='agentlog', cls='lee-agentlog'),
        Div(Input(id='agentprompt', cls='lee-input lee-prompt',
                  placeholder='ask leela to do something…  (ctrl+enter)'),
            cls='lee-promptbar'),
        cls='lee-panel lee-agent')


def _footer():
    "Always-visible keys plus status."
    ks = [k for k in (list(by_scope('global')) + list(by_scope('editor'))) if k.show == 'footer']
    kids = [Span(Kbd(k.keys[0]), Span(k.label), cls='lee-fkey') for k in ks]
    return Footer(*kids, Span(cls='lee-spacer'), Span(id='status', cls='lee-status'), cls='lee-footer')


def _shell(ws, gate):
    "The whole app body; every structural route returns this so the client re-mounts consistently."
    return Div(
        _header(ws),
        Div(
            Aside(_files_panel(ws), _toast_panel(), cls='lee-left', id='left'),
            Div(cls='lee-split', data_split='left'),
            Div(_editor_pane(ws), Div(cls='lee-hsplit'), _exec_strip(),
                _term_panel(gate), _agent_panel(), cls='lee-centre'),
            Div(cls='lee-split', data_split='right'),
            Aside(_vars_panel(ws), cls='lee-right', id='right'),
            cls='lee-body'),
        _footer(),
        id='shell', cls='lee-app')


# ---------------------------------------------------------------------------
# app
# ---------------------------------------------------------------------------
def ide_app(ws: Workspace, gate: TerminalGate = None):
    # Registering makes asking possible: with nobody listening `Approvals` refuses every
    # gated write immediately rather than parking the model's thread on an answer that is
    # never coming. The browser counts as a listener for as long as the app is served.
    ws.approvals.listen()
    "Build the FastHTML IDE around an open workspace. `gate` decides who may open a terminal."
    gate = gate or TerminalGate()
    # Everything is served from disk. FastHTML's default headers pull htmx and friends
    # from a CDN, which would make a local IDE need the network to start -- and fail
    # outright behind a proxy or on a plane. `default_hdrs=False` plus the vendored
    # bundles keeps it self-contained, the same reason CodeMirror is vendored.
    hdrs = (Link(rel='icon', href='/leestatic/favicon.svg', type='image/svg+xml'),
            Script(src='/leestatic/htmx.min.js'),
            Script(src='/leestatic/lee-cm6.js'),
            Script(src='/leestatic/lee-term.js'),
            Link(rel='stylesheet', href='/leestatic/lee-term.css'),
            Link(rel='stylesheet', href='/leestatic/lee-ide.css'),
            Script(src='/leestatic/lee-ide.js', defer=True))

    def _term_cwd(ref=None):
        "Where a new terminal starts. Ergonomics, not confinement -- a shell can `cd` anywhere."
        if ref:
            try: return ws.fs._check(ref, must_exist=True)
            except Exception: pass
        return ws.fs.roots[0] if ws.fs.roots else None

    async def term_ws(sock):
        """One websocket, one pty. Binary frames are keystrokes; text frames are control.

        The split is what keeps the protocol free of escaping: a pty's traffic is
        arbitrary bytes, so anything that needs *structure* (the opening handshake, a
        resize) travels as text and everything else is passed through untouched.
        """
        await sock.accept()
        t = key = None
        try:
            hello = json.loads((await sock.receive()).get('text') or '{}')
            gate.check(hello.get('token'))          # raises unless this connection may have a pty
            kind = hello.get('kind', 'shell')
            cwd = _term_cwd(hello.get('cwd'))
            argv = lazygit_argv(cwd) if kind == 'git' else None
            key = hello.get('id') or kind
            t = ws.terms.open(key, argv=argv, cwd=cwd,
                              cols=int(hello.get('cols') or 80), rows=int(hello.get('rows') or 24))
        except Exception as e:
            await sock.send_text(json.dumps({'t': 'error', 'error': errstr(e)}))
            await sock.close()
            return

        async def to_browser(data): await sock.send_bytes(data)

        async def from_browser():
            while True:
                m = await sock.receive()
                if m['type'] == 'websocket.disconnect': return
                if (b := m.get('bytes')) is not None: t.write(b)
                elif (s := m.get('text')) is not None:
                    c = json.loads(s)
                    if c.get('t') == 'size': t.resize(c.get('cols', 80), c.get('rows', 24))

        pump = asyncio.create_task(t.stream(to_browser))
        recv = asyncio.create_task(from_browser())
        try:
            await asyncio.wait({pump, recv}, return_when=asyncio.FIRST_COMPLETED)
            if pump.done():                          # the child exited; say so before closing
                ws.terms.close(key)
                try: await sock.send_text(json.dumps({'t': 'exit', 'note': t.exit_note}))
                except Exception: pass
        finally:
            for task in (pump, recv):
                if not task.done(): task.cancel()
            try: await sock.close()
            except Exception: pass

    app, rt = fast_app(pico=False, default_hdrs=False, hdrs=hdrs,
                       routes=(Mount('/leestatic', StaticFiles(directory=str(static_dir()))),
                               WebSocketRoute('/term/ws', term_ws)))

    # Open notebooks, keyed by tab. The server holds the document so structural
    # edits and runs stay consistent across reloads of the page.
    _docs: dict[str, Notebook] = {}

    def _doc():
        t = ws.tab
        return None if t is None else _docs.get(t.path or t.title)

    async def _k(): return await ws.kernel()

    async def _api(path, params=None, timeout=15):
        "Proxy one inspector call on the active tab's kernel; None when it has no server."
        k = await _k()
        return await k.api(path, params, timeout) if k else None

    # -- shell -------------------------------------------------------------
    @rt('/')
    def home():
        return Title('leela'), _shell(ws, gate)

    @rt('/keys.json')
    def keys_json(): return JSONResponse({'keys': web_keymap(), 'help': help_rows()})


    # -- files -------------------------------------------------------------
    @rt('/tree')
    def tree(path: str):
        try: return tuple(_tree_node(e) for e in ws.fs.ls(path))
        except Exception as e: return Div(errstr(e), cls='lee-err')

    @rt('/fs/add_root')
    def add_root(path: str):
        try: ws.add_root(path); ws.save()
        except Exception as e: return _fail(str(e))
        return _shell(ws, gate)

    @rt('/fs/new')
    async def fs_new(req):
        "Create a file or folder. `kind` is 'file' or 'dir'."
        d = await req.json()
        parent, name, kind = d.get('parent') or '', d.get('name') or '', d.get('kind', 'file')
        if not name: return _fail('name required')
        try:
            target = Path(parent)/name
            e = ws.fs.mkdir(target) if kind == 'dir' else ws.fs.touch(target)
            return {'ok': True, 'entry': e.dict()}
        except Exception as e: return _fail(e)

    @rt('/fs/rename')
    async def fs_rename(req):
        d = await req.json()
        try: return {'ok': True, 'entry': ws.fs.rename(d['path'], d['name']).dict()}
        except Exception as e: return _fail(e)

    @rt('/fs/delete')
    async def fs_delete(req):
        d = await req.json()
        try:
            ws.fs.delete(d['path'])
            if (i := ws.find(d['path'])) is not None: ws.close(i)
            return {'ok': True}
        except Exception as e: return _fail(e)

    @rt('/fs/find')
    def fs_find(q: str = '', limit: int = 200):
        "Quick-open: fuzzy match over every file in the open folders, best match first."
        hits = fuzzy_rank(q, ws.fs.walk(), key=str, limit=limit)
        return {'hits': [{'path': str(p), 'name': p.name, 'lang': lang_for(p) or ''} for p in hits]}

    # -- tabs --------------------------------------------------------------
    # Tab routes swap only the tab bar, never the whole shell. Re-rendering everything
    # for a tab switch would collapse the file tree, drop the exec editor and reset the
    # variable panel -- the client re-mounts just the editor when #tabbar changes.
    @rt('/tab/open')
    def tab_open(path: str):
        try: ws.open(path); ws.save()
        except Exception as e: return Div(errstr(e), cls='lee-err')
        return _tab_bar(ws)

    @rt('/tab/select')
    def tab_select(i: int):
        ws.activate(i)
        return _tab_bar(ws)

    @rt('/tab/close')
    def tab_close(i: int):
        ws.close(i); ws.save()
        return _tab_bar(ws)

    @rt('/tab/new')
    def tab_new(kind: str = 'notebook'):
        ws.new_scratch(kind)
        return _tab_bar(ws)

    @rt('/tab/state')
    def tab_state():
        "Everything the client needs to mount the active tab's editor."
        t = ws.tab
        if t is None: return {'kind': None}
        if t.kind == 'notebook':
            try: nb = Notebook.load(t.path) if t.path else Notebook.blank()
            except Exception as e: return {'kind': 'error', 'error': errstr(e)}
            _docs[t.path or t.title] = nb
            return {'kind': 'notebook', 'path': t.path, 'title': t.title, 'dirty': t.dirty,
                    'cells': [c.dict() for c in nb.cells]}
        try: text = ws.fs.read(t.path) if t.path else ''
        except Exception as e: return {'kind': 'error', 'error': errstr(e)}
        return {'kind': 'text', 'path': t.path, 'title': t.title, 'lang': t.lang or '', 'text': text}

    # -- notebooks ---------------------------------------------------------
    @rt('/nb/run')
    async def nb_run(req):
        "Run one cell against the tab's kernel and return its outputs."
        d = await req.json()
        nb, i = _doc(), int(d.get('i', 0))
        if nb is None: return _fail('no notebook open')
        if 0 <= i < len(nb): nb[i].source = d.get('source', nb[i].source)
        k = await _k()
        c = await nb.run(i, k)
        if ws.tab: ws.tab.dirty = True
        return {'ok': not c.has_error, 'i': i, 'cell': c.dict()}

    @rt('/nb/ask')
    async def nb_ask(req):
        """Run a prompt cell: the assistant answers, with the notebook above it as context.

        Off the loop like every other model call, and slow enough that it has to be --
        the file tree must keep responding while the answer is being written.
        """
        d = await req.json()
        nb, i = _doc(), int(d.get('i', 0))
        if nb is None: return _fail('no notebook open')
        if not (0 <= i < len(nb)): return _fail(f'no cell {i}')
        nb[i].source = d.get('source', nb[i].source)
        try: c = await _off_loop(ws.ask_cell, nb, i)
        except Exception as e: return _fail(e)
        if ws.tab: ws.tab.dirty = True
        return {'ok': ws.ai.ready, 'i': i, 'cell': c.dict(), 'note': ws.ai.note,
                'cells': [x.dict() for x in nb.cells],   # approval/compaction cells may have landed
                'activity': ws.ai.activity.rows(mark=ws.ai.activity._mark),
                'edits': [{'path': p, **_diff(was, now)} for p, (was, now) in ws.ai.changes().items()]}

    @rt('/nb/edit')
    async def nb_edit(req):
        "Structural edits: insert / delete / move / type / split / merge."
        d = await req.json()
        nb = _doc()
        if nb is None: return _fail('no notebook open')
        op, i = d.get('op'), int(d.get('i', 0))
        if op == 'insert': nb.insert(i, Cell(source=d.get('source', ''), cell_type=d.get('cell_type', 'code')))
        elif op == 'delete': nb.delete(i)
        elif op == 'move': nb.move(i, int(d.get('d', 1)))
        elif op == 'type':
            nb.cycle_type(i) if d.get('cycle') else nb.set_type(i, d.get('cell_type', 'code'))
        elif op == 'split': nb.split(i, int(d.get('offset', 0)))
        elif op == 'merge': nb.merge(i)
        elif op == 'source':
            nb[i].source = d.get('source', '')
            nb.dirty = True
        elif op == 'clear': nb.clear_all()
        else: return _fail(f'unknown op {op!r}')
        if ws.tab: ws.tab.dirty = nb.dirty
        return {'ok': True, 'cells': [c.dict() for c in nb.cells]}

    @rt('/nb/save')
    async def nb_save(req):
        d = await req.json()
        t = ws.tab
        if t is None: return _fail('nothing open')
        try:
            if t.kind == 'notebook':
                nb = _doc()
                if nb is None: return _fail('no notebook')
                for c in d.get('cells', []):
                    if 0 <= c['i'] < len(nb): nb[c['i']].source = c['source']
                nb.save(t.path or d.get('path'), sandbox=ws.fs)
            else:
                ws.fs.write(t.path, d.get('text', ''))
            t.dirty = False
            return {'ok': True, 'path': t.path}
        except Exception as e:
            return _fail(e)

    @rt('/diff')
    async def diff_route(req):
        """What the editor holds, against what is on disk.

        The dirty dot says *that* a tab changed; this says what changed, which is the
        question actually worth answering before a save -- or after the assistant or
        lazygit has been at the file underneath the buffer.
        """
        d = await req.json()
        t = ws.tab
        if t is None: return _fail('nothing open')
        disk = ws.disk_text(t)
        if disk is None: return _fail(f'{t.title} has never been saved')
        if t.kind == 'notebook':
            nb = _doc()
            if nb is None: return _fail('no notebook open')
            for c in d.get('cells', []):
                if 0 <= c['i'] < len(nb): nb[c['i']].source = c['source']
            buf = nb.source_text()
        else:
            buf = d.get('text', '')
        return {'path': t.path, 'title': t.title, **_diff(disk, buf)}

    # -- exec strip --------------------------------------------------------
    @rt('/exec')
    async def exec_route(req):
        """Run the exec box. `live` shares the tab's kernel namespace; `isolated` goes to the
        agent sandbox, where writes really are discarded."""
        d = await req.json()
        code, scope = (d.get('code') or '').strip(), d.get('scope', 'live')
        if not code: return {'ok': True, 'text': '', 'outputs': []}
        k = await _k()
        if scope == 'isolated':
            r = await k.api('/agent/api/exec', {'code': code, 'scope': 'isolated'})
            if r is None: return {'ok': False, 'text': 'no sandbox on this kernel', 'outputs': []}
            txt = r.get('stdout') or ''
            if r.get('result'): txt += (('\n' if txt else '') + (r['result'].get('value') or ''))
            err = await _explain(k, r.get('error'), 'isolated')
            return {'ok': bool(r.get('ok')), 'text': (err or txt or 'ok'), 'scope': 'isolated'}
        res = await k.execute(code)
        return {'ok': res.ok, 'text': await _explain(k, res.error) or res.text or 'ok',
                'outputs': res.outputs, 'count': res.execution_count, 'scope': 'live'}

    @rt('/exec/history')
    async def exec_history(n: int = 200):
        "The rolling history notebook, oldest first -- what ctrl+up/down cycles through."
        r = await _api('/api/history', {'n': n})
        return {'cells': (r or {}).get('cells', [])}

    @rt('/complete')
    async def complete_route(req, pos: int = 0):
        "Completions from the kernel, so venv modules complete like they do in a real shell."
        d = await req.json()
        k = await _k()
        try: return await k.complete(d.get('code', ''), int(d.get('pos', pos)))
        except Exception: return {'from': pos, 'matches': []}

    @rt('/complete/ai')
    async def ai_complete_route(req):
        """One inline suggestion from the local model, for what belongs at the cursor.

        Never fired by typing: it costs a forward pass, and the kernel's own completions
        above are instant and know the real namespace. This answers the other question --
        what the next few lines should *say*.
        """
        d = await req.json()
        c = ws.completer
        text = await _off_loop(c.complete, d.get('code', ''), int(d.get('pos', 0)),
                               d.get('lang') or 'python')
        return {'text': text, 'note': c.note, 'ready': c.ready}

    @rt('/inspect')
    async def inspect_route(req):
        "Signature and docstring for the name at the cursor, from the object that is actually loaded."
        d = await req.json()
        k = await _k()
        txt = await k.inspect_obj(d.get('code', ''), int(d.get('pos', 0)), int(d.get('detail', 0))) if k else ''
        return {'text': txt, 'note': '' if txt else 'the kernel knows nothing about that name'}

    # -- variables (proxied from the kernel's own inspector) ---------------
    @rt('/vars')
    async def vars_route(profile: str = 'minimal', sort: str = 'recent', scope: str = 'live'):
        base = '/agent/api/rows' if scope == 'isolated' else '/api/rows'
        r = await _api(base, {'profile': profile, 'sort': sort})
        return r or {'groups': [], 'error': 'no kernel inspector'}

    @rt('/vars/expand')
    async def vars_expand(accessor: str, offset: int = 0, scope: str = 'live'):
        base = '/agent/api/expand' if scope == 'isolated' else '/api/expand'
        return JSONResponse(await _api(base, {'accessor': accessor, 'offset': offset}) or [])

    @rt('/vars/grid')
    async def vars_grid(accessor: str, roff: int = 0, coff: int = 0, scope: str = 'live'):
        base = '/agent/api/grid' if scope == 'isolated' else '/api/grid'
        return JSONResponse(await _api(base, {'accessor': accessor, 'roff': roff, 'coff': coff}))

    @rt('/vars/set')
    async def vars_set(req):
        d = await req.json()
        r = await _api('/api/set', {'accessor': d['accessor'], 'expr': d['expr']})
        return r or {'ok': False, 'error': 'no kernel inspector'}

    @rt('/vars/promote')
    async def vars_promote(accessor: str):
        r = await _api('/api/promote', {'accessor': accessor})
        return r or {'ok': False, 'error': 'no kernel inspector'}

    # -- code search -------------------------------------------------------
    @rt('/search')
    def search_route(q: str = '', regex: bool = False, limit: int = 60):
        "Search the open folders. `backend` says which engine answered, so an empty result is never a mystery."
        return _found(ws, ws.search.search(q, limit=limit, regex=regex))

    @rt('/outline')
    def outline_route(path: str):
        return {'symbols': [h.dict() for h in ws.search.symbols(path)]}

    @rt('/similar')
    def similar_route(path: str, line: int = 1, mode: str = 'cluster', limit: int = 25):
        """Code like the function at `path:line`.

        `mode=cluster` answers "the family this belongs to" via usearch clustering;
        `mode=knn` answers "the N closest things". The first is usually what you want
        when hunting for every place a pattern was already implemented.
        """
        fn = ws.search.peers if mode == 'cluster' else ws.search.similar
        return _found(ws, fn(path, line, limit=limit))

    @rt('/clusters')
    def clusters_route(limit: int = 40):
        "An ANN clustering of the whole indexed corpus -- a map of the codebase by shape."
        cs = ws.search.clusters()
        return {'note': ws.search.note, 'clusters': [c.dict() for c in cs[:limit]]}

    # -- terminal & git ----------------------------------------------------
    @rt('/term/info')
    def term_info():
        """What the client needs to open a terminal, including the token.

        The token is handed out over this same-origin route and nowhere else. That is the
        whole point: a websocket is not bound by the same-origin policy, so any page the
        user visits can reach `127.0.0.1` -- only one that can *read* this response is the IDE.
        """
        try: lazygit_argv(); git, git_why = True, ''
        except LazygitMissing as e: git, git_why = False, str(e)
        return {'enabled': gate.enabled, 'why': gate.why, 'token': gate.token if gate.enabled else '',
                'cwd': str(_term_cwd() or ''), 'lazygit': git, 'lazygit_why': git_why,
                'open': [t.state() for t in ws.terms.all()]}

    @rt('/term/close')
    def term_close(id: str = 'shell'):
        ws.terms.close(id)
        return {'ok': True}

    # -- research ----------------------------------------------------------
    @rt('/research/search')
    async def research_search(q: str = '', n: int = 15):
        "Web search: titles and urls only, so it stays fast enough to drive from a prompt box."
        docs = await _off_loop(ws.research.search, q, n)
        return {'note': ws.research.note, 'docs': [d.dict() for d in docs]}

    @rt('/research/read')
    async def research_read(url: str = ''):
        "One page (or GitHub file, or arxiv paper) as markdown."
        d = await _off_loop(ws.research.read, url)
        return {'note': ws.research.note, 'doc': d.dict() if d else None}

    @rt('/research/dig')
    async def research_dig(q: str = '', n: int = 5):
        "Search and read the top results into one cited digest."
        docs, digest = await _off_loop(ws.research.dig, q, n)
        return {'note': ws.research.note, 'digest': digest, 'docs': [d.dict() for d in docs]}

    @rt('/research/save')
    async def research_save(req):
        "Keep a fetched page: markdown by default, or a runnable notebook with kind='notebook'."
        d = await req.json()
        try:
            if d.get('kind') == 'notebook':
                e = await _off_loop(ws.research.save_notebook, d['url'], d.get('path'))
            else:
                from ..research import Doc
                doc = Doc(title=d.get('title') or '', url=d.get('url') or '', text=d.get('text') or '')
                e = await _off_loop(ws.research.save, doc, d.get('path'))
            if e is None: return _fail(ws.research.note)
            return {'ok': True, 'entry': e.dict(), 'note': ws.research.note}
        except Exception as e: return _fail(e)

    # -- dev servers -------------------------------------------------------
    @rt('/dev/list')
    def dev_list(): return {'servers': [s.state() for s in ws.dev.all()]}

    @rt('/dev/start')
    async def dev_start(path: str):
        "Run a python web app under a live inspector; its module globals become another env."
        try:
            p = ws.fs._check(path, must_exist=True)
            s = await ws.dev.start(p)
            return {'ok': s.alive, **s.state(), 'log': s.tail(20)}
        except Exception as e:
            return _fail(e)

    @rt('/dev/stop')
    async def dev_stop(path: str):
        await ws.dev.stop(path)
        return {'ok': True}

    @rt('/dev/log')
    def dev_log(path: str, n: int = 60):
        s = ws.dev.get(path)
        return {'log': s.tail(n) if s else [], **(s.state() if s else {})}

    # -- what the assistant can see ---------------------------------------
    @rt('/screen')
    async def screen(req):
        """Park a screenshot to go with the next question.

        The capture itself has to happen in the browser -- `getDisplayMedia` needs a user
        gesture and a real window server, neither of which a server-side grab has. So the
        page sends the frame here, and it waits in the workspace until something asks.
        """
        d = await req.json()
        url = d.get('data_url') or ''
        if not url.startswith('data:image'): return _fail('no image in that capture')
        import base64
        try: png = base64.b64decode(url.split(',', 1)[1])
        except Exception as e: return _fail(e)
        ws.put_screen(png=png, note='a screenshot from the browser')
        return {'ok': True, 'bytes': len(png)}

    # -- agent -------------------------------------------------------------
    @rt('/agent/info')
    async def agent_info(): return await _api('/agent/api/info') or {'mode': 'off'}

    @rt('/agent/transcript')
    async def agent_transcript(): return await _api('/agent/api/transcript') or {'cells': []}

    @rt('/agent/status')
    def agent_status():
        """Whether the assistant is loaded, what model it is on, and what it is doing right now.

        Polled while a turn runs, which is why `activity` is in here: an agentic loop that
        shows nothing for forty seconds is indistinguishable from a hang, and the client
        renders these rows as they arrive. `approval` is in the same payload so a write
        waiting on a person is picked up by the poll already in flight rather than needing
        a channel of its own.
        """
        return ws.ai.status()

    @rt('/agent/stop')
    def agent_stop():
        "Ask the model to stop generating. The turn in flight returns whatever it already had."
        try:
            if ws.ai.cancel(): return {'ok': True}
            return {'ok': False, 'error': 'the assistant is not running'}
        except Exception as e:
            return {'ok': False, 'error': errstr(e)}

    @rt('/agent/approval')
    def agent_approval():
        "The write waiting for a person, or None. The client shows this as a card, not a modal."
        a = ws.pending_approval
        return {'pending': a.dict() if a is not None else None}

    @rt('/agent/approve')
    async def agent_approve(req):
        """Answer a pending approval. `note` is the reason, and the reason goes back to the model.

        Refusing with a reason is the point of the whole mechanism: "no, that file is
        generated, edit the notebook instead" redirects the agent, where a bare denial just
        makes it try the same edit again.
        """
        d = await req.json()
        a = ws.answer_approval(d.get('id') or '', bool(d.get('ok')), (d.get('note') or '').strip())
        if a is None: return _fail('nothing is waiting for an answer')
        return {'ok': True, 'answer': a.dict()}

    @rt('/agent/command')
    async def agent_command(req):
        "Run a slash command (`/model`, `/cost`, `/compact`, `/skills`, `/tools`, `/reload`)."
        d = await req.json()
        line = (d.get('line') or '').strip()
        if not line: return {'ok': True, 'text': 'commands: ' + ', '.join('/' + c for c in ws.ai.commands())}
        out = await _off_loop(ws.ai.command, line)
        if out is None: return _fail(f'unknown command {line.split()[0]}')
        return {'ok': True, 'text': out}

    @rt('/agent/ask')
    async def agent_ask(req):
        """One turn with the assistant.

        The model runs on a worker thread and its tools call straight back into this
        workspace, so an edit it makes is on disk by the time the reply arrives.

        What comes back with the reply is a *diff per changed file*, taken from disk on
        either side of each write rather than from what the tools reported. That is the
        difference between the model's account of its work and the work: a tool result is
        a claim, and the file is the fact. It also lets the client decide whether
        reloading the tab would throw away something the user typed while it was thinking.
        """
        d = await req.json()
        q = (d.get('prompt') or '').strip()
        if not q: return _fail('nothing to ask')
        a = ws.ai
        text = await _off_loop(ws.ask, q)      # `ws.ask` attaches any pending screen capture
        return {'ok': a.ready, 'text': text, 'note': a.note,
                'activity': a.activity.rows(mark=a.activity._mark),
                'usage': repr(a.use), 'model': a.model.name,
                'edits': [{'path': p, **_diff(was, now)} for p, (was, now) in a.changes().items()]}

    # -- kernel control ----------------------------------------------------
    @rt('/kernel/interrupt')
    async def k_interrupt():
        k = ws.kernel_peek()
        if k: await k.interrupt()
        return {'ok': True}

    @rt('/kernel/restart')
    async def k_restart():
        k = ws.kernel_peek()
        if k: await k.restart()
        return {'ok': True, 'base': k.base if k else None}

    @rt('/kernel/info')
    async def k_info():
        k = await _k()
        return {'alive': bool(k and k.alive), 'base': k.base if k else None,
                'pid': k.pid if k else None, 'key': ws.kernel_key(),
                'boot_error': k.boot_error if k else None}

    return app


def serve_ide(roots=(), port=5001, host='127.0.0.1', agent='restricted', kernel_port=8400,
              open_ws=True, allow_remote_terminal=False, kernel='ipykernel',
              model=None, approvals='ask'):
    "Start the web IDE over `roots` (or the saved workspace when none are given)."
    import uvicorn
    kw = dict(port=kernel_port, agent=agent, kernel=kernel, model=model, approvals=approvals)
    ws = Workspace.load(**kw) if (open_ws and not roots) else Workspace(**kw)
    for r in roots: ws.add_root(r)
    if not ws.fs.roots: ws.add_root(os.getcwd())
    gate = TerminalGate(host=host, allow_remote=allow_remote_terminal)
    app = ide_app(ws, gate)
    print(f'leela  http://{host}:{port}   folders: ' + ', '.join(p.name for p in ws.fs.roots))
    if not gate.enabled: print(f'  {gate.why}')
    uvicorn.run(app, host=host, port=port, log_level='warning')
