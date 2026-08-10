"""The web vocabulary every block shares: error shape, streaming frames, static URLs.

These were module-level helpers in `leela/web/app.py` with leading underscores, which was
right while there was one web module. Blocks need them, and a block importing a private
name out of the module it is being extracted from is not an improvement -- so they move
here and lose the underscore.

`leela/web/app.py` re-exports the old names, because `tests/` and any external caller
import some of them from there.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastcore.aio import athreaded
from fasthtml.common import JSONResponse

from .. import errstr

__all__ = ['static_dir', 'asset', 'fail', 'sse', 'off_loop', 'diff_payload', 'found',
           'pipeline_socket']


def static_dir():
    "Web assets in a normal install, py2app Resources, or a py2exe distribution."
    import sys
    candidates = [Path(__file__).parent.parent/'web'/'static']
    if getattr(sys, 'frozen', False):
        exe = Path(sys.executable).resolve()
        candidates += [exe.parent/'leela'/'web'/'static',
                       exe.parent.parent/'Resources'/'leela'/'web'/'static']
    return next((p for p in candidates if p.exists()), candidates[0])


def asset(name):
    "A static URL that changes when the local asset does, preventing mixed JS/CSS revisions."
    p = static_dir()/name
    try: version = p.stat().st_mtime_ns
    except OSError: version = 0
    return f'/leestatic/{name}?v={version}'


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
    """Register a websocket that shows one pipeline's terminal.

    Shared because a release, a deploy and a driven part are the same thing on the wire: a
    JSON hello carrying the terminal token, then raw bytes both ways, which is exactly what
    `/term/ws` speaks and therefore what the browser's xterm already knows how to render.

    `resolve(hello)` returns the pipeline the connection is about. It is a callback rather
    than an object because the pipelines are per project and per kind, and which one a viewer
    wants is in the hello it has not sent yet.

    A raw Starlette route on purpose: FastHTML's own `ws` wrapper injects parameters by name
    and would hand the handler `None` instead of the socket, and a pty needs the socket.
    """
    import asyncio
    import json

    from starlette.routing import WebSocketRoute

    async def handler(sock):
        # Imported here rather than closed over: `tests/test_route_owners` reads a route's
        # owner out of its closure, and a module-level helper captured here would make this
        # socket look as though `leela` itself served it instead of the block that
        # registered it.
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
        try:
            await asyncio.wait({send, recv}, return_when=asyncio.FIRST_COMPLETED)
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
    from ..diffs import diff_label, diff_rows, udiff
    return {'label': diff_label(was, now), 'rows': [r.dict() for r in diff_rows(udiff(was, now))]}


def found(search, hits):
    """A hit list plus the backend that produced it -- an empty result is never a mystery.

    Takes the search service rather than the workspace: a block that only searches should
    not need a whole `Workspace` to shape its reply, and this is the seam `SearchPort`
    substitutes at.
    """
    return {'backend': search.backend, 'note': search.note, 'hits': [h.dict() for h in hits]}
