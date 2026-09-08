"The canvas as routes: open, run, react, wire, save, the basket, the change, and one helper turn."

from __future__ import annotations
from fasthtml.common import StreamingResponse, JSONResponse
from starlette.responses import FileResponse, PlainTextResponse
from fastcore.all import Path
from ...core.web import fail, off_loop, sse
from .bricks import libraries, locate, mount, palette, wire as brick_wire
from .change import bundles, coverage, place_diff, pr, review, state, value
from .context import SCOPES, Spec, resolve, spec_of, weigh
from .doc import Canvas
from .explain import explain
from .layout import arrange
from .lit import lit
from .helper import Ask, helper_for
from .ops import apply_op
from .store import Stale, Untrusted, brick_host, canvas_dir, store_for
from . import ui

__all__ = ['CAPS', 'connect', 'page', 'branch_page', 'canvas_path', 'Outside', 'SUFFIX']

CAPS = ('fs', 'ai', 'pool')   # `pool` is the kernel a canvas's code runs in
#: What a canvas file is called. The document is markdown, so anything can read it.
SUFFIX = '.canvas.md'

def _settle(o, touched_names, skip=()):
    "Rerun what the change made stale, and re-resolve every binding that reads it."
    return o.runtime.react(o.canvas.bricks, touched_names, skip=skip)

#: Kinds whose body is code the runtime executes.
RUNNING_KINDS = ('code', 'data')

def _runs_code(o, op):
    """Whether this op would execute or evaluate something in the document's namespace.

    Authoring is not running. `insert` executes only a body it is given, `bind` resolves the
    expression it is handed, and `run` and `values` are the two that always do. `replace`,
    `remove`, `kind`, `move` and `replace_selection` retire names and move prose about, so an
    untrusted document is still editable: this gate refused an empty code brick and made a
    document you could read but not write in.
    """
    op = op or {}
    kind = op.get('op')
    if kind in ('run', 'values'): return True
    if kind == 'bind': return bool(op.get('expr') or op.get('binds'))
    if kind == 'insert':
        return bool((op.get('body') or '').strip()) and op.get('kind') in RUNNING_KINDS \
            or bool(op.get('binds'))
    return False

def _ports(o):
    return {b.id: o.runtime.bindings(b) for b in o.canvas if b.binds}

def _payload(o):
    return {'ok': True, 'canvas': o.canvas.dict(), 'ports': _ports(o), 'trail': o.trail,
            'names': o.runtime.names(), 'trusted': o.trusted, 'rev': o.rev}

def connect(app, ctx=None):
    rt = app.route
    libs = libraries()
    notes = mount(app, libs)          # a library serves its own gallery, frame and data routes
    def ctx_fs():
        "The workspace filesystem, and None in the spike, which has no `ctx` and no open folder."
        return None if ctx is None else ctx.fs
    def ctx_pool():
        "The kernel pool a canvas's code runs in. None is the spike, which runs in this process."
        return None if ctx is None else ctx.pool
    #: Read per request, not once: the store follows the roots the workspace has open now.
    def store(): return store_for(ctx_fs(), pool=ctx_pool())
    @rt('/canvas/palette')
    def canvas_palette():
        "Every brick every installed library offers. Empty with a note when none is installed."
        return {**palette(libs), 'mount_notes': notes}
    @rt('/canvas/brick')
    def canvas_brick(src: str):
        "One brick's row: its ports, what it emits, and which library it came from."
        lib, b = locate(src, libs)
        if lib is None: return fail(f'no brick for {src!r}')
        return {'ok': True, 'library': lib.name, 'brick': b}
    @rt('/canvas/wire')
    def canvas_wire(src: str, base: str = ''):
        "The wiring this brick ships, for a code brick above it. `base` adds the remote fallback."
        got = wire(src, libs, base)
        return got if got.get('ok') else fail(got.get('error', 'no wiring'))
    @rt('/canvas/state')
    def canvas_state(path: str):
        "The document as the browser draws it."
        try: return _load(ctx_fs(), path).dict()
        except Exception as e: return fail(e)
    @rt('/canvas/context')
    def canvas_context(path: str, id: str, scope: str = '', budget: int = 0):
        "The exact basket one question will send, with the rule that put each item there."
        try:
            doc = _load(ctx_fs(), path)
            base = spec_of(doc.by_id(id))
            spec = Spec(scope=scope or base.scope, pins=base.pins, mutes=base.mutes,
                        budget=budget or base.budget, goal=base.goal)
            items = resolve(doc, id, spec)
            return {'scopes': list(SCOPES), 'spec': spec.__dict__,
                    'items': [i.dict() for i in items], **weigh(items)}
        except Exception as e: return fail(e)
    @rt('/canvas/changes')
    def canvas_changes(path: str, base: str = ''):
        "Every change in the document, against what a diff says moved."
        try:
            doc = _load(ctx_fs(), path)
            changed = _changed(doc, base)
            return {'changed': changed, **coverage(doc, changed),
                    'state': {b.id: state(b, changed) for b in bundles(doc)}}
        except Exception as e: return fail(e)
    @rt('/canvas/review')
    def canvas_review(path: str, id: str, base: str = ''):
        "One change as a document of its own, built from the diff."
        try:
            doc = _load(ctx_fs(), path)
            return review(doc, id, _diff(doc, base)).dict()
        except Exception as e: return fail(e)
    @rt('/canvas/value')
    def canvas_value(path: str, base: str = ''):
        "Every goal, and every change that serves it."
        try:
            doc = _load(ctx_fs(), path)
            return value(doc, _changed(doc, base)).dict()
        except Exception as e: return fail(e)
    @rt('/canvas/pr')
    def canvas_pr(path: str, id: str):
        "The pull request one change is worth. It opens nothing."
        try: return pr(_load(ctx_fs(), path), id)
        except Exception as e: return fail(e)
    @rt('/canvas/page')
    async def canvas_page(path: str, out: str = '', base: str = ''):
        "The literate page, written beside the document unless `out` says otherwise."
        try:
            doc = _load(ctx_fs(), path)
            dest = canvas_path(ctx_fs(), out, must_exist=False, suffix='') if out \
                   else Path(doc.path).with_suffix('.html')
            return {'ok': True, **await off_loop(page, doc, dest, base)}
        except Exception as e: return fail(e)
    @rt('/canvas/draft')
    async def canvas_draft(req):
        "Draft the missing snippet prose, and save the document with it."
        d = await req.json()
        try:
            doc = _load(ctx_fs(), d.get('path') or '')
            ask = lambda prompt, brick: ctx.ai.ask(prompt)
            got = await off_loop(explain, doc, ask, str(Path(doc.path).parent),
                                 ('snippet', 'diff'), bool(d.get('overwrite')))
            doc.save()
            return {'ok': True, 'drafted': [b.id for b in got]}
        except Exception as e: return fail(e)


    @rt('/canvas')
    def canvas_index(req):
        files = store().files()
        path = req.query_params.get('path') or (str(files[0]) if files else '')
        return ui.page(path, [str(p) for p in files], brick_host())

    @rt('/canvas/js')
    def canvas_js(): return PlainTextResponse(ui.bundle(), media_type='text/javascript')

    @rt('/canvas/css')
    def canvas_css(): return PlainTextResponse((Path(__file__).parent/'canvas.css').read_text(), media_type='text/css')

    @rt('/canvas/list')
    def canvas_list(): return JSONResponse({'ok': True, 'files': [str(p) for p in store().files()],
                                            'dir': str(canvas_dir())})

    @rt('/canvas/file')
    def canvas_file(path: str):
        "A file a brick embeds, resolved under the canvas directory and nowhere else."
        root = Path(canvas_dir()).resolve()
        p = (root/path).resolve()
        if not p.is_relative_to(root) or not p.is_file(): return fail('not under the canvas directory', 404)
        return FileResponse(p)

    @rt('/canvas/wire/{name}')
    def canvas_wire_named(name: str):
        "The wiring for one brick, by bare name. What the wiring panel asks for."
        got = brick_wire(name, libs, base=brick_host())
        return JSONResponse(got) if got.get('ok') else fail(got.get('error', 'no wiring'))

    @rt('/canvas/open')
    def canvas_open(path: str, fresh: str = ''):
        try: p = canvas_path(ctx_fs(), path)
        except FileNotFoundError: return fail(f'no canvas at {path}')
        except Exception as e: return fail(e)
        o = store().reopen(p) if fresh else store().get(p)
        return JSONResponse({**_payload(o), 'runs': {}, 'host': brick_host()})

    @rt('/canvas/trust')
    async def canvas_trust(req):
        """Say this document's code may run, then run it.

        A canvas is markdown, so it arrives from a clone, a download or a paste. Opening one used
        to execute every code brick in it before anybody had read a line.
        """
        d = await req.json()
        try: o = store().get(canvas_path(ctx_fs(), d['path']))
        except Exception as e: return fail(e)
        runs = await off_loop(o.allow)
        return JSONResponse({'ok': True, 'trusted': True, 'runs': runs, 'ports': _ports(o)})

    @rt('/canvas/op')
    async def canvas_op(req):
        d = await req.json()
        try: o = store().get(canvas_path(ctx_fs(), d['path']))
        except Exception as e: return fail(e)
        if _runs_code(o, d['op']):
            try: o.must_trust()
            except Untrusted as e: return fail(f'{e}; trust it first', 403)
        r = await off_loop(apply_op, o.canvas, o.runtime, d['op'])
        if not r.get('ok'): return fail(r.get('error', 'op failed'))
        o.bump()
        return JSONResponse({**r, 'ports': _ports(o), 'canvas': o.canvas.dict(), 'rev': o.rev})

    @rt('/canvas/runall')
    async def canvas_runall(req):
        "Every code brick, in dependency order. What the button means, and what opening does."
        d = await req.json()
        try: o = store().get(canvas_path(ctx_fs(), d['path']))
        except Exception as e: return fail(e)
        try: o.must_trust()
        except Untrusted as e: return fail(f'{e}; trust it first', 403)
        for id, src in (d.get('sources') or {}).items():
            b = o.canvas.by_id(id)
            if b is not None and b.runs: b.body = src
        runs = await off_loop(o.runtime.run_all, o.canvas.bricks)
        return JSONResponse({'ok': True, 'runs': runs, 'ports': await off_loop(_ports, o)})

    @rt('/canvas/run')
    async def canvas_run(req):
        d = await req.json()
        try: o = store().get(canvas_path(ctx_fs(), d['path']))
        except Exception as e: return fail(e)
        b = o.canvas.by_id(d['id'])
        if b is None or not b.runs: return fail('not a code brick')
        try: o.must_trust()
        except Untrusted as e: return fail(f'{e}; trust it first', 403)
        if 'source' in d: b.body = d['source']
        r = await off_loop(o.runtime.run, b)
        #: Only the bindings that moved. Handing back every port would post props to every frame,
        #: and a frame that takes props redraws, which restarts anything animating in it.
        settled = await off_loop(_settle, o, r['defs'], [b.id])
        return JSONResponse({'ok': True, 'id': b.id, 'run': r, **settled})

    @rt('/canvas/emit')
    async def canvas_emit(req):
        "A component handing a value back. The namespace takes it and the document catches up."
        d = await req.json()
        try: o = store().get(canvas_path(ctx_fs(), d['path']))
        except Exception as e: return fail(e)
        try: o.must_trust()
        except Untrusted as e: return fail(f'{e}; trust it first', 403)
        await off_loop(o.runtime.set, d['name'], d['value'])
        settled = await off_loop(_settle, o, [d['name']], d.get('from', ''))
        return JSONResponse({'ok': True, 'name': d['name'], **settled})

    @rt('/canvas/save')
    async def canvas_save(req):
        "The destination passes the same gate as the source, so a save cannot write out of the tree."
        d = await req.json()
        try:
            fs = ctx_fs()
            o = store().get(canvas_path(fs, d['path']))
            o.check(d.get('rev'))
            dest = canvas_path(fs, d['to'], must_exist=False) if d.get('to') else Path(o.canvas.path)
        except Stale as e: return fail(f'{e}; reopen before saving', 409)
        except Exception as e: return fail(e)
        p = o.canvas.save(dest)
        return JSONResponse({'ok': True, 'path': str(p), 'bytes': p.stat().st_size, 'rev': o.rev})

    @rt('/canvas/steer')
    async def canvas_steer(req):
        d = await req.json()
        try: o = store().get(canvas_path(ctx_fs(), d['path']))
        except Exception as e: return fail(e)
        await o.queue(d['turn']).put(d['text'])
        return JSONResponse({'ok': True})

    @rt('/canvas/ask/stream')
    async def canvas_ask(req):
        d = await req.json()
        try: o = store().get(canvas_path(ctx_fs(), d['path']))
        except Exception as e: return fail(e)
        turn = d.get('turn') or 'turn'
        ask = Ask(question=d.get('question', ''), canvas=o.canvas, runtime=o.runtime,
                  brick_id=d.get('id', ''), selection=d.get('selection', ''), nth=int(d.get('nth') or 0),
                  palette=palette(libs)['bricks'],
                  trail=list(o.trail), mode=o.canvas.meta.get('mode', 'make'))
        o.remember(ask.question, ask.brick_id, ask.selection)
        helper = helper_for(_assistant(ctx))
        q = o.queue(turn)

        async def stream():
            reply, ops = '', []
            try:
                async for event, data in helper.turn(ask, q):
                    if event == 'chunk': reply += data['text']
                    if event == 'answer':
                        r = apply_op(o.canvas, o.runtime, {'op': 'answer', 'of': ask.brick_id, 'markdown': data['markdown']})
                        ops.append(r); yield sse('op', r)
                        continue
                    if event == 'op':
                        r = apply_op(o.canvas, o.runtime, {**data, 'op': data['op']})
                        if r.get('ok') and data.get('wire'): r = _wire_from_host(o, r, libs)
                        ops.append(r); yield sse('op', r)
                        continue
                    yield sse(event, data)
                yield sse('done', {'reply': reply, 'ops': ops, 'canvas': o.canvas.dict(),
                                   'ports': _ports(o), 'trail': o.trail})
            except Exception as e: yield sse('error', {'text': f'{type(e).__name__}: {e}'})
            finally: o.close_turn(turn)
        return StreamingResponse(stream(), media_type='text/event-stream')

def _assistant(ctx):
    """The workspace's assistant when a model is configured, else None for the stand-in.

    The browser used to decide this by sending `model`, which `helper.js` never sent, so every ask
    reached the scripted stand-in however the workspace was configured.
    """
    if ctx is None: return None
    try: ai = ctx.ai
    except Exception: return None
    return ai if getattr(ai, 'ready', False) else None

def _wire_from_host(o, r, libs=None):
    "Take the snippet the component's own package ships, put it above the brick, and bind the ports."
    src = (r.get('brick') or {}).get('attrs', {}).get('src', '')
    w = brick_wire(src, libs, base=brick_host())
    if not w.get('ok'): return {**r, 'wire_error': w.get('error', f'no wiring for {src!r}')}
    at = o.canvas.index(r['brick']['id'])
    if at is None: at = len(o.canvas)
    extra = []
    if w.get('wire'):
        code = apply_op(o.canvas, o.runtime, {'op': 'insert', 'at': at, 'kind': 'code', 'body': w['wire']})
        cb = o.canvas.by_id(code['brick']['id'])
        run = code.get('run') or o.runtime.run(cb)      # `insert` already ran it; running twice
        if w.get('remote') and any(x.get('ename') in ('ModuleNotFoundError', 'ImportError') for x in run['outputs']):
            cb.body = w['remote']
            run = o.runtime.run(cb)
        extra.append({**code, 'run': run, 'brick': cb.dict()})
    b = o.canvas.by_id(r['brick']['id'])
    b.binds = {port: expr for port, expr in (w.get('binds') or {}).items()}
    if w.get('height'): b.props['height'] = str(w['height'])
    return {**r, 'brick': b.dict(), 'wired': extra, 'at': o.canvas.index(b.id)}

class Outside(Exception):
    "A path that resolves outside everything this block may touch."

def canvas_path(fs, path, must_exist=True, suffix=SUFFIX):
    """The one gate every route passes a path through, source and destination alike.

    With a folder open the workspace decides, so a canvas cannot reach past `fs.roots`. With none
    open, which is the spike and the tests, the canvas directory decides. Neither answers a
    relative path by walking up: `resolve` compares the resolved path against the root it must be
    under.
    """
    if fs is not None and getattr(fs, 'roots', None):
        p = fs._check(path, must_exist=must_exist)
    else:
        root = Path(canvas_dir()).resolve()
        raw = Path(path).expanduser()
        p = (raw if raw.is_absolute() else root/raw).resolve()
        if not p.is_relative_to(root): raise Outside(f'{p} is outside {root}')
        if must_exist and not p.is_file(): raise FileNotFoundError(str(p))
    if suffix and not str(p).endswith(suffix): raise ValueError(f'not a canvas: {p}')
    return p

def _load(fs, path):
    return arrange(Canvas.load(canvas_path(fs, path)))

def _root(doc):
    "Where a `snippet` brick's path starts: the repository, else the document's folder."
    from gheasy.repo import repo_root
    here = Path(doc.path).parent
    return str(repo_root(here) or here)

def _diff(doc, base='', paths=(), right=''):
    "The diff a review reads. Git is `gheasy`'s, so this asks it rather than shelling out."
    from gheasy.repo import GitRepo, repo_root
    root = repo_root(Path(doc.path).parent)
    if root is None: return ''
    g = GitRepo(root)
    ask = lambda path: g.diff(path=path, left=base, right=right)
    return '\n'.join(ask(p) for p in paths) if paths else ask('')

def _changed(doc, base=''):
    from .change import hunks
    return list(hunks(_diff(doc, base)))

def _demote(b):
    "A review's own `## Change` under eight reviews is a third-level heading, not a section."
    if b.kind == 'text' and b.body.strip().startswith('## '): b.body = '#' + b.body.strip()
    return b

def branch_page(
    doc,           # the document, its bundles carrying the paths and the prose
    dest,          # where to write the page
    base='',       # what each bundle's diff is taken against
):
    """Every bundle as a review, stitched into one page: each file's hunks under the prose about it.

    `page` fills a `diff` slot and hands back a run of files. `review` pairs them: for each file in
    a bundle's diff it emits the hunks and then every `snippet`, `note` or `text` brick that cites
    that path. So a document that explains its files is a literate diff, and this is the whole
    branch read that way rather than one slot with every file under it.
    """
    changed = _changed(doc, base)
    out = Canvas(meta={'title': doc.title}, path=doc.path)
    for g in doc.of('goal'): out.add(g)
    for i, b in enumerate(bundles(doc)):
        r = review(doc, b.id, _diff(doc, base, b.paths, ''))
        for brick in r.bricks:
            #: One document out of many reviews, and `add` refuses a repeated id.
            brick.id = f'b{i}-{brick.id}'
            out.add(_demote(brick))
    sub = (f'Generated by canvas.branch_page from {Path(doc.path).name}. Every hunk is a real git '
           f'diff against {base or "the working tree"}, and the prose under it cites that file.')
    loose = coverage(doc, changed)['unclaimed']
    got = lit(arrange(out), dest, changed=changed, root=_root(doc), subtitle=sub, unclaimed=loose)
    return {'path': str(got), 'changed': changed, 'unclaimed': loose,
            'reviews': [b.id for b in bundles(doc)]}

def page(
    doc,           # the document, its `diff` bricks still empty
    dest,          # where to write the page
    base='',       # what the file list is diffed against
):
    "The literate page: fill the diff a document asks for, then render it."
    place_diff(doc, lambda paths, left, right: _diff(doc, left or base, paths, right))
    changed = _changed(doc, base)
    root = _root(doc)
    sub = (f'Generated by canvas.lit from {Path(doc.path).name}. Every snippet is read from the '
           'file it names.')
    out = lit(doc, dest, changed=changed, root=root, subtitle=sub)
    return {'path': str(out), 'changed': changed,
            'unclaimed': coverage(doc, changed)['unclaimed'],
            'diffs': [b.id for b in doc.of('diff')]}
