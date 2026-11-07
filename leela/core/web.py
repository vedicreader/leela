"The web vocabulary every block shares: error shape, streaming frames, static URLs."

from __future__ import annotations

import asyncio, json
from contextlib import suppress
from pathlib import Path

from fastcore.aio import athreaded
from fastcore.basics import first, ifnone
from fasthtml.common import JSONResponse
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.staticfiles import StaticFiles

from .. import errstr

__all__ = ['asset_dir', 'static_dirs', 'Assets', 'asset', 'fail', 'NOT_OBJECT', 'JsonBody', 'json_obj', 'sse', 'off_loop', 'unless_gone',
           'diff_payload', 'found', 'pipeline_socket', 'IDE_BUNDLES']

#: Client bundles in execution order. They share one lexical scope, so `lee-core.js` declares the vocabulary and the rest read it.
IDE_BUNDLES = ('lee-core.js', 'lee-agent.js', 'lee-ide.js')

def asset_dir(name):
    "One of leela's asset dirs, in a normal install, py2app Resources, or a py2exe distribution."
    import sys
    candidates = [Path(__file__).parent.parent/name]
    if getattr(sys, 'frozen', False):
        exe = Path(sys.executable).resolve()
        candidates += [exe.parent/'leela'/name, exe.parent.parent/'Resources'/'leela'/name]
    return ifnone(first(p for p in candidates if p.exists()), candidates[0])

def static_dirs():
    "The asset dirs behind `/leestatic`, in lookup order: authored `static/`, vendored `vendor/`."
    return [asset_dir('static'), asset_dir('vendor')]

def asset(name):
    "A static URL that changes when the local asset does, preventing mixed JS/CSS revisions."
    p = first(d/name for d in static_dirs() if (d/name).is_file())
    return f'/leestatic/{name}?v={p.stat().st_mtime_ns if p else 0}'

HAND, HAND_URL = 'Patrick Hand', '/leefonts/'   # the hand font of the board's paper (OFL), from Leela's own rupaka, as abhyasa serves it

def hand_css() -> str:
    "rupaka's `@font-face` rules of the hand font, linked from `HAND_URL`."
    from rupaka.render import font_css
    return '\n'.join(l for l in font_css(base=HAND_URL).splitlines() if f"'{HAND}'" in l)

def hand_url() -> str:
    "The URL of `hand_css`, which changes with rupaka's version."
    import rupaka
    return f'{HAND_URL}hand.css?v={rupaka.__version__}'

def hand_routes():
    "The routes of `HAND_URL`: `hand.css`, and rupaka's font files."
    from rupaka.render import assets
    from starlette.responses import Response
    from starlette.routing import Mount, Route
    css = hand_css()
    return [Route(HAND_URL + 'hand.css', lambda req: Response(css, media_type='text/css', headers={'Cache-Control': 'max-age=86400'})),
            Mount(HAND_URL.rstrip('/'), StaticFiles(directory=str(assets().fonts), check_dir=False))]

BOARD_URL = '/leeboard/'   # the screen guide's board, from Leela's own rupaka (`rupaka.board`)

def board_url(name) -> str:
    "The URL of the board file `name` (`board.js`, `board.css`, `texparts.js`), which changes with rupaka's version; `libs/` for the folder of the pens."
    import rupaka
    return BOARD_URL + name + ('' if name.endswith('/') else f'?v={rupaka.__version__}')

def board_routes():
    "The routes of `BOARD_URL`: rupaka's board bundles, its formula parts and the folder of its pens (`host.assets`)."
    from rupaka.board import assets, bundle
    from starlette.responses import Response
    from starlette.routing import Mount, Route
    a, cache = assets(), {'Cache-Control': 'max-age=86400'}
    js, css, tex = bundle('js'), bundle('css'), a.tex.read_text()
    page = lambda text, mime: lambda req: Response(text, media_type=mime, headers=cache)
    return [Route(BOARD_URL + 'board.js', page(js, 'text/javascript')), Route(BOARD_URL + 'board.css', page(css, 'text/css')),
            Route(BOARD_URL + 'texparts.js', page(tex, 'text/javascript')), Mount(BOARD_URL + 'libs', StaticFiles(directory=str(a.libs), check_dir=False))]

def three_routes():
    "`/leestatic/three.js`, where rupaka's `R.need('three')` looks beside `lee-rupaka.js`: rupaka's three.js, built on first request."
    from rupaka.render import bundle
    from starlette.responses import Response
    from starlette.routing import Route
    return [Route('/leestatic/three.js', lambda req: Response(bundle('three'), media_type='text/javascript', headers={'Cache-Control': 'max-age=86400'}))]

class Assets:
    "Serve one URL prefix from several directories, first match winning."
    def __init__(self, *dirs):
        self.dirs = [Path(d) for d in dirs]
        self.apps = [StaticFiles(directory=str(d)) for d in self.dirs]
    async def __call__(self, scope, receive, send):
        rel = scope['path'].removeprefix(scope.get('root_path') or '').lstrip('/')
        served = first(a for d, a in zip(self.dirs, self.apps) if (d/rel).is_file())
        return await ifnone(served, self.apps[0])(scope, receive, send)

def fail(err, code=400, kind=None, **extra):
    "The IDE's JSON error shape. `err` is an exception (reported `Type: message`) or a ready string; `kind` is what a screen can offer."
    # `said` is an error already worded for a person, so it goes without its type name.
    body = {'ok': False, 'error': getattr(err, 'said', None) or (errstr(err) if isinstance(err, Exception) else str(err))}
    # The kernel ceiling is the one failure a person can answer, so it travels with what to offer.
    if getattr(err, 'limit', None): body |= {'kernel_limit': err.limit, 'candidate': err.candidate}
    if isinstance(err, Exception) and getattr(err, 'kind', None): body |= {'kind': err.kind, 'refs': list(getattr(err, 'refs', ()))}
    if kind: body['kind'] = kind
    return JSONResponse(body | extra, status_code=code)

NOT_OBJECT = 'The request body is not a JSON object.'

async def json_obj(req):
    "The JSON object in the body of `req`, or None for an empty, unreadable or non-object body."
    try: d = json.loads(await req.body())
    except ValueError: return None
    return d if isinstance(d, dict) else None

class JsonBody:
    "Answer `fail` 400 for a JSON body that is not an object, before FastHTML parses it into a 500."
    def __init__(self, app): self.app = app
    async def __call__(self, scope, receive, send):
        ctype = Headers(scope=scope).get('content-type', '') if scope['type'] == 'http' else ''
        if ctype.split(';')[0].strip().lower() != 'application/json': return await self.app(scope, receive, send)
        body = await Request(scope, receive).body()
        try: ok = not body or isinstance(json.loads(body), dict)
        except ValueError: ok = False
        if not ok: return await fail(NOT_OBJECT)(scope, receive, send)
        sent = False
        async def replay():
            nonlocal sent
            if sent: return await receive()
            sent = True
            return {'type': 'http.request', 'body': body, 'more_body': False}
        await self.app(scope, replay, send)

def sse(event, data):
    "One server-sent event. Newlines in the payload would end the frame, so it goes as JSON."
    return f'event: {event}\ndata: {json.dumps(data)}\n\n'

@athreaded
def off_loop(fn, *a, **kw):
    "Run blocking research, indexing and model work on fastcore's worker thread."
    return fn(*a, **kw)

async def unless_gone(req, coro, every=.25):
    "`coro`'s result, or None once the client behind `req` hangs up; either way `coro` does not outlive the request."
    task = asyncio.ensure_future(coro)
    try:
        while not task.done():
            await asyncio.wait({task}, timeout=every)
            if not task.done() and await req.is_disconnected(): return None
        return task.result()
    finally:
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError): await task

def pipeline_socket(app, path, gate, resolve):
    "Register a websocket that shows one pipeline's terminal; `resolve(hello)` names which one."
    import asyncio, json
    from starlette.routing import WebSocketRoute
    async def handler(sock):
        from .. import errstr
        await sock.accept()
        pipeline = q = None
        try:
            hello = json.loads((await sock.receive()).get('text') or '{}')
            gate.check(hello.get('token'))
            pipeline = resolve(hello)
            pipeline.resize(int(hello.get('cols') or 100), int(hello.get('rows') or 30))
            q = pipeline.subscribe()
        except Exception as e:
            await sock.send_text(json.dumps({'t': 'error', 'error': errstr(e)}))
            await sock.close()
            return
        async def to_browser():
            # `None` is the end of the run: say so, the way `/term/ws` does, so the view knows.
            while (data := await q.get()) is not None: await sock.send_bytes(data)
            await sock.send_text(json.dumps({'t': 'exit', 'note': getattr(pipeline, 'exit_note', '')}))
        async def from_browser():
            while True:
                m = await sock.receive()
                if m['type'] == 'websocket.disconnect': return
                if (b := m.get('bytes')) is not None: pipeline.write(b)
                elif (text := m.get('text')) is not None:
                    c = json.loads(text)
                    if c.get('t') == 'size': pipeline.resize(c.get('cols', 100), c.get('rows', 30))
        send = asyncio.create_task(to_browser())
        recv = asyncio.create_task(from_browser())
        try: await asyncio.wait({send, recv}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            pipeline.unsubscribe(q)
            for task in (send, recv):
                if not task.done(): task.cancel()
            try: await sock.close()
            except Exception: pass
    app.router.routes.append(WebSocketRoute(path, handler))
    return handler

def diff_payload(was, now, path=None):
    "One text-vs-text comparison in the shape every diff surface in the client consumes; rows carry coloured code when `path` names the language."
    from .text import diff_label, diff_rows, path_lang, udiff
    return {'label': diff_label(was, now), 'rows': [r.dict() for r in diff_rows(udiff(was, now), path_lang(path))]}

def found(search, hits):
    "A hit list plus the backend that produced it, so an empty result is never a mystery."
    return {'backend': search.backend, 'note': search.note, 'hits': [h.dict() for h in hits]}
