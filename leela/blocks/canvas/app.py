"The canvas as routes: open, run, react, wire, save, and one streaming helper turn."

from __future__ import annotations
import asyncio, json, urllib.request
from fasthtml.common import StreamingResponse, JSONResponse
from starlette.responses import PlainTextResponse
from fastcore.all import Path, first
from ...core.web import fail, sse
from .doc import Brick, Canvas
from .helper import Ask, helper_for
from .live import Runtime
from .ops import apply_op
from .store import Store, brick_host, canvas_dir
from . import ui

__all__ = ['CAPS', 'connect', 'STORE']

CAPS = ('ai',)
STORE = Store()

def _settle(o, touched_names):
    "Rerun what the change made stale, and re-resolve every binding that reads it."
    return o.runtime.react(o.canvas.bricks, touched_names)

def _ports(o):
    return {b.id: o.runtime.bindings(b) for b in o.canvas if b.binds}

def _payload(o):
    return {'ok': True, 'canvas': o.canvas.dict(), 'ports': _ports(o), 'trail': o.trail,
            'names': sorted(k for k in o.runtime.ns if not k.startswith('_'))}

def _palette():
    "The bricks the component host publishes. One fetch, cached for the life of the process."
    if _palette.cache is None:
        try:
            with urllib.request.urlopen(f'{brick_host()}/bricks/manifest.json', timeout=4) as r:
                _palette.cache = json.load(r)
        except Exception as e: _palette.cache = {'bricks': [], 'groups': {}, 'error': str(e)}
    return _palette.cache
_palette.cache = None

def connect(app, ctx=None):
    rt = app.route

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

    @rt('/canvas/wire/{name}')
    def canvas_wire(name: str):
        "The component host's wiring for one brick, proxied so the document stays same-origin."
        try:
            with urllib.request.urlopen(f'{brick_host()}/bricks/wire/{name}', timeout=4) as r:
                return JSONResponse(json.load(r))
        except Exception as e: return fail(f'no component host: {e}')

    @rt('/canvas/palette')
    def canvas_palette(): return JSONResponse(_palette())

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
        names = r.get('run', {}).get('defs') or []
        return JSONResponse({**r, 'ports': _ports(o), 'canvas': o.canvas.dict()})

    @rt('/canvas/run')
    async def canvas_run(req):
        d = await req.json()
        o = STORE.get(d['path'])
        b = o.canvas.by_id(d['id'])
        if b is None or not b.runs: return fail('not a code brick')
        if 'source' in d: b.body = d['source']
        r = o.runtime.run(b)
        return JSONResponse({'ok': True, 'id': b.id, 'run': r, **_settle(o, r['defs']), 'ports': _ports(o)})

    @rt('/canvas/emit')
    async def canvas_emit(req):
        "A component handing a value back. The namespace takes it and the document catches up."
        d = await req.json()
        o = STORE.get(d['path'])
        o.runtime.set(d['name'], d['value'])
        return JSONResponse({'ok': True, 'name': d['name'], **_settle(o, [d['name']]), 'ports': _ports(o)})

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
                  brick_id=d.get('id', ''), selection=d.get('selection', ''),
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
                        if r.get('ok') and data.get('wire'): r = _wire_from_host(o, r)
                        ops.append(r); yield sse('op', r)
                        continue
                    yield sse(event, data)
                yield sse('done', {'reply': reply, 'ops': ops, 'canvas': o.canvas.dict(),
                                   'ports': _ports(o), 'trail': o.trail})
            except Exception as e: yield sse('error', {'text': f'{type(e).__name__}: {e}'})
            finally: o.close_turn(turn)
        return StreamingResponse(stream(), media_type='text/event-stream')

def _wire_from_host(o, r):
    "Take the snippet the component's own package ships, put it above the brick, and bind the ports."
    src = (r.get('brick') or {}).get('attrs', {}).get('src', '')
    name = src.split(':')[-1]
    try:
        with urllib.request.urlopen(f'{brick_host()}/bricks/wire/{name}', timeout=4) as h: w = json.load(h)
    except Exception as e: return {**r, 'wire_error': str(e)}
    at = o.canvas.index(r['brick']['id'])
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
