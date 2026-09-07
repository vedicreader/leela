"The canvas as routes: open, run, react, wire, save, the basket, the change, and one helper turn."

from __future__ import annotations
import asyncio, json
from fasthtml.common import StreamingResponse, JSONResponse
from starlette.responses import FileResponse, PlainTextResponse
from fastcore.all import Path, first
from ...core.web import fail, off_loop, sse
from .bricks import libraries, locate, mount, palette, wire as brick_wire
from .change import bundles, coverage, pr, review, state, value
from .context import SCOPES, Spec, resolve, spec_of, weigh
from .doc import Brick, Canvas
from .explain import capture, explain, replay
from .layout import arrange
from .lit import lit
from .helper import Ask, helper_for
from .live import Runtime
from .ops import apply_op
from .store import Store, brick_host, canvas_dir
from . import ui

__all__ = ['CAPS', 'connect', 'STORE', 'SUFFIX']

CAPS = ('fs', 'ai')
STORE = Store()
#: What a canvas file is called. The document is markdown, so anything can read it.
SUFFIX = '.canvas.md'

def _settle(o, touched_names, skip=()):
    "Rerun what the change made stale, and re-resolve every binding that reads it."
    return o.runtime.react(o.canvas.bricks, touched_names, skip=skip)

def _ports(o):
    return {b.id: o.runtime.bindings(b) for b in o.canvas if b.binds}

def _payload(o):
    return {'ok': True, 'canvas': o.canvas.dict(), 'ports': _ports(o), 'trail': o.trail,
            'names': sorted(k for k in o.runtime.ns if not k.startswith('_'))}

def connect(app, ctx=None):
    rt = app.route
    libs = libraries()
    notes = mount(app, libs)          # a library serves its own gallery, frame and data routes
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
        try: return _load(ctx.fs, path).dict()
        except Exception as e: return fail(e)
    @rt('/canvas/context')
    def canvas_context(path: str, id: str, scope: str = '', budget: int = 0):
        "The exact basket one question will send, with the rule that put each item there."
        try:
            doc = _load(ctx.fs, path)
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
            doc = _load(ctx.fs, path)
            changed = _changed(doc, base)
            return {'changed': changed, **coverage(doc, changed),
                    'state': {b.id: state(b, changed) for b in bundles(doc)}}
        except Exception as e: return fail(e)
    @rt('/canvas/review')
    def canvas_review(path: str, id: str, base: str = ''):
        "One change as a document of its own, built from the diff."
        try:
            doc = _load(ctx.fs, path)
            return review(doc, id, _diff(doc, base)).dict()
        except Exception as e: return fail(e)
    @rt('/canvas/value')
    def canvas_value(path: str, base: str = ''):
        "Every goal, and every change that serves it."
        try:
            doc = _load(ctx.fs, path)
            return value(doc, _changed(doc, base)).dict()
        except Exception as e: return fail(e)
    @rt('/canvas/pr')
    def canvas_pr(path: str, id: str):
        "The pull request one change is worth. It opens nothing."
        try: return pr(_load(ctx.fs, path), id)
        except Exception as e: return fail(e)
    @rt('/canvas/page')
    async def canvas_page(path: str, out: str = '', base: str = ''):
        "The literate page, written beside the document unless `out` says otherwise."
        try:
            doc = _load(ctx.fs, path)
            root = Path(doc.path).parent
            dest = Path(out) if out else Path(doc.path).with_suffix('.html')
            p = await off_loop(lit, doc, dest, _changed(doc, base), str(root))
            return {'ok': True, 'path': str(p)}
        except Exception as e: return fail(e)
    @rt('/canvas/draft')
    async def canvas_draft(req):
        "Draft the missing snippet prose, and save the document with it."
        d = await req.json()
        try:
            doc = _load(ctx.fs, d.get('path') or '')
            ask = lambda prompt, brick: ctx.ai.ask(prompt)
            got = await off_loop(explain, doc, ask, str(Path(doc.path).parent),
                                 ('snippet', 'diff'), bool(d.get('overwrite')))
            doc.save()
            return {'ok': True, 'drafted': [b.id for b in got]}
        except Exception as e: return fail(e)


    @rt('/canvas')
    def canvas_index(req):
        files = STORE.files()
        path = req.query_params.get('path') or (str(files[0]) if files else '')
        return ui.page(path, [str(p) for p in files], brick_host())

    @rt('/canvas/js')
    def canvas_js(): return PlainTextResponse(ui.bundle(), media_type='text/javascript')

    @rt('/canvas/css')
    def canvas_css(): return PlainTextResponse((Path(__file__).parent/'canvas.css').read_text(), media_type='text/css')

    @rt('/canvas/list')
    def canvas_list(): return JSONResponse({'ok': True, 'files': [str(p) for p in STORE.files()],
                                            'dir': str(canvas_dir())})

    @rt('/canvas/file')
    def canvas_file(path: str):
        "A file a brick embeds, resolved under the canvas directory and nowhere else."
        root = Path(canvas_dir()).resolve()
        p = (root/path).resolve()
        if not str(p).startswith(str(root)) or not p.is_file(): return fail('not under the canvas directory', 404)
        return FileResponse(p)

    @rt('/canvas/wire/{name}')
    def canvas_wire_named(name: str):
        "The wiring for one brick, by bare name. What the wiring panel asks for."
        got = brick_wire(name, libs, base=brick_host())
        return JSONResponse(got) if got.get('ok') else fail(got.get('error', 'no wiring'))

    @rt('/canvas/open')
    def canvas_open(path: str, fresh: str = ''):
        if not Path(path).is_file(): return fail(f'no canvas at {path}')
        o = STORE.reopen(path) if fresh else STORE.get(path)
        return JSONResponse({**_payload(o), 'runs': {b.id: {'ok': True} for b in o.canvas if b.runs},
                             'host': brick_host()})

    @rt('/canvas/op')
    async def canvas_op(req):
        d = await req.json()
        o = STORE.get(d['path'])
        r = apply_op(o.canvas, o.runtime, d['op'])
        if not r.get('ok'): return fail(r.get('error', 'op failed'))
        return JSONResponse({**r, 'ports': _ports(o), 'canvas': o.canvas.dict()})

    @rt('/canvas/runall')
    async def canvas_runall(req):
        "Every code brick, in dependency order. What the button means, and what opening does."
        d = await req.json()
        o = STORE.get(d['path'])
        for id, src in (d.get('sources') or {}).items():
            b = o.canvas.by_id(id)
            if b is not None and b.runs: b.body = src
        runs = o.runtime.run_all(o.canvas.bricks)
        return JSONResponse({'ok': True, 'runs': runs, 'ports': _ports(o)})

    @rt('/canvas/run')
    async def canvas_run(req):
        d = await req.json()
        o = STORE.get(d['path'])
        b = o.canvas.by_id(d['id'])
        if b is None or not b.runs: return fail('not a code brick')
        if 'source' in d: b.body = d['source']
        r = o.runtime.run(b)
        #: Only the bindings that moved. Handing back every port would post props to every frame,
        #: and a frame that takes props redraws, which restarts anything animating in it.
        return JSONResponse({'ok': True, 'id': b.id, 'run': r, **_settle(o, r['defs'], skip=[b.id])})

    @rt('/canvas/emit')
    async def canvas_emit(req):
        "A component handing a value back. The namespace takes it and the document catches up."
        d = await req.json()
        o = STORE.get(d['path'])
        o.runtime.set(d['name'], d['value'])
        return JSONResponse({'ok': True, 'name': d['name'], **_settle(o, [d['name']], skip=d.get('from', ''))})

    @rt('/canvas/save')
    async def canvas_save(req):
        d = await req.json()
        o = STORE.get(d['path'])
        p = o.canvas.save(d.get('to') or d['path'])
        return JSONResponse({'ok': True, 'path': str(p), 'bytes': p.stat().st_size})

    @rt('/canvas/steer')
    async def canvas_steer(req):
        d = await req.json()
        o = STORE.get(d['path'])
        await o.queue(d['turn']).put(d['text'])
        return JSONResponse({'ok': True})

    @rt('/canvas/ask/stream')
    async def canvas_ask(req):
        d = await req.json()
        o = STORE.get(d['path'])
        turn = d.get('turn') or 'turn'
        ask = Ask(question=d.get('question', ''), canvas=o.canvas, runtime=o.runtime,
                  brick_id=d.get('id', ''), selection=d.get('selection', ''), nth=int(d.get('nth') or 0),
                  palette=palette(libs)['bricks'],
                  trail=list(o.trail), mode=o.canvas.meta.get('mode', 'make'))
        o.remember(ask.question, ask.brick_id, ask.selection)
        helper = helper_for(ctx.ai if ctx is not None and d.get('model') else None)
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
        run = o.runtime.run(cb)
        if w.get('remote') and any(x.get('ename') in ('ModuleNotFoundError', 'ImportError') for x in run['outputs']):
            cb.body = w['remote']
            run = o.runtime.run(cb)
        extra.append({**code, 'run': run, 'brick': cb.dict()})
    b = o.canvas.by_id(r['brick']['id'])
    b.binds = {port: expr for port, expr in (w.get('binds') or {}).items()}
    if w.get('height'): b.props['height'] = str(w['height'])
    return {**r, 'brick': b.dict(), 'wired': extra, 'at': o.canvas.index(b.id)}

def _load(fs, path):
    p = fs._check(path, must_exist=True)
    if not str(p).endswith(SUFFIX): raise ValueError(f'not a canvas: {p}')
    return arrange(Doc.load(p))

def _diff(doc, base=''):
    "The diff a review reads. Git is `gheasy`'s, so this asks it rather than shelling out."
    from gheasy.repo import GitRepo, repo_root
    root = repo_root(Path(doc.path).parent)
    if root is None: return ''
    return GitRepo(root).diff(left=base) if base else GitRepo(root).diff()

def _changed(doc, base=''):
    from .change import hunks
    return list(hunks(_diff(doc, base)))
