"""The web vocabulary every block shares: error shape, streaming frames, static URLs.

`leela/app.py` re-exports the old underscored names, which `tests/` and external callers
still import from there.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastcore.aio import athreaded
from fastcore.basics import first, ifnone
from fasthtml.common import JSONResponse
from starlette.staticfiles import StaticFiles

from .. import errstr

__all__ = ['asset_dir', 'static_dirs', 'Assets', 'asset', 'fail', 'sse', 'off_loop',
           'diff_payload', 'found', 'pipeline_socket']


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


class Assets:
    "Serve one URL prefix from several directories, first match winning."
    # Starlette's `Mount` does not fall through when the app behind it 404s, so two mounts on
    # `/leestatic` would shadow rather than combine.

    def __init__(self, *dirs):
        self.dirs = [Path(d) for d in dirs]
        self.apps = [StaticFiles(directory=str(d)) for d in self.dirs]

    async def __call__(self, scope, receive, send):
        # `Mount` leaves `scope['path']` absolute and reports the matched prefix as `root_path`.
        # `removeprefix` agrees either way: a Starlette that rewrites `path` to be mount-relative
        # leaves nothing to remove.
        rel = scope['path'].removeprefix(scope.get('root_path') or '').lstrip('/')
        served = first(a for d, a in zip(self.dirs, self.apps) if (d/rel).is_file())
        return await ifnone(served, self.apps[0])(scope, receive, send)   # else the first one 404s


def fail(err, code=400):
    "The IDE's JSON error shape. `err` is an exception (reported `Type: message`) or a ready string."
    return JSONResponse({'ok': False, 'error': errstr(err) if isinstance(err, Exception) else str(err)},
                        status_code=code)


def sse(event, data):
    "One server-sent event. Newlines in the payload would end the frame, so it goes as JSON."
    return f'event: {event}\ndata: {json.dumps(data)}\n\n'


@athreaded
def off_loop(fn, *a, **kw):
    "Run blocking research, indexing and model work on fastcore's worker thread."
    return fn(*a, **kw)


def pipeline_socket(app, path, gate, resolve):
    "Register a websocket that shows one pipeline's terminal; `resolve(hello)` names which one."
    # A raw Starlette route on purpose: FastHTML's `ws` wrapper injects parameters by name and
    # would hand the handler `None` instead of the socket, and a pty needs the socket.
    import asyncio, json

    from starlette.routing import WebSocketRoute

    async def handler(sock):
        # Imported here rather than closed over: `tests/test_route_owners` reads a route's owner
        # out of its closure, and a captured module-level helper would name `leela` as the owner
        # instead of the block that registered this socket.
        from .. import errstr
        await sock.accept()
        pipeline = q = None
        try:
            hello = json.loads((await sock.receive()).get('text') or '{}')
            gate.check(hello.get('token'))          # the same boundary a pty always has
            pipeline = resolve(hello)
            pipeline.resize(int(hello.get('cols') or 100), int(hello.get('rows') or 30))
            q = pipeline.subscribe()
        except Exception as e:
            await sock.send_text(json.dumps({'t': 'error', 'error': errstr(e)}))
            await sock.close()
            return

        async def to_browser():
            while True: await sock.send_bytes(await q.get())

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


def diff_payload(was, now):
    "One text-vs-text comparison in the shape every diff surface in the client consumes."
    from .diffs import diff_label, diff_rows, udiff
    return {'label': diff_label(was, now), 'rows': [r.dict() for r in diff_rows(udiff(was, now))]}


def found(search, hits):
    "A hit list plus the backend that produced it -- an empty result is never a mystery."
    return {'backend': search.backend, 'note': search.note, 'hits': [h.dict() for h in hits]}
