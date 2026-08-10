"""The release pipeline, and the one terminal it runs on.

The state lives in this closure, one `Release` per project root, because a pipeline is a
*running thing*: a request that starts a step and a websocket that shows its output have to
be talking about the same pty, and a per-request object could not be. `Release` itself owns
the sequencing; this file is the door to it.

`/release/ws` speaks the same protocol as `/term/ws` -- a JSON hello carrying the terminal
token, then raw bytes both ways -- so the browser renders it with the same xterm component,
in the same theme, with the same keyboard. It is a separate socket rather than a `kind` on
the existing one because the pty is not opened by whoever attaches: the pipeline starts it,
keeps pumping it whether or not anyone is watching, and replays what has already scrolled by
to each new viewer. A pty nobody reads stops the child mid-write, and "the release hung
because the panel was closed" is the failure this arrangement exists to prevent.
"""

from __future__ import annotations

import asyncio
import json

from starlette.routing import WebSocketRoute

from ... import errstr
from ...core.web import fail, off_loop
from ...envs import EnvStore
from ...releases import Release, ReleaseError
from ...repos import repo_for

__all__ = ['CAPS', 'connect']

CAPS = ('fs', 'gate')


def connect(app, ctx):
    rt = app.route
    pipelines = {}

    def release(target=''):
        "The pipeline for one project, made once and then kept -- it has a process in it."
        root = repo_for(ctx.session, target)
        key = str(root)
        if key not in pipelines:
            pipelines[key] = Release(root, env=EnvStore())
        # The interpreter can change after the pipeline was made -- picking a project venv
        # in the kernel picker must retarget the next step, not the next restart.
        pipelines[key].python = ctx.session.pool.default_python
        return pipelines[key]

    @rt('/releases')
    def releases_info(repo: str = ''):
        try: return release(repo).state()
        except Exception as e: return fail(e)

    @rt('/releases/action')
    async def releases_action(req):
        """One explicit move: start, retry a step, skip it, stop, forget, or edit the plan.

        `start` returns as soon as the first step is *running*, not when the pipeline
        finishes. The state it returns says which step that is, and the terminal says the
        rest -- a release that took four minutes must not be a four-minute request.
        """
        d = await req.json()
        op = str(d.get('op') or '')
        try:
            r = release(d.get('repo') or '')
            if op == 'start': return await r.start(d.get('step') or '', bool(d.get('auto', True)))
            if op == 'step': return await r.start(d.get('step') or '', False)
            if op == 'stop': return r.stop()
            if op == 'skip': return r.skip(d.get('step') or '')
            if op == 'reset': return r.reset()
            if op == 'save': return r.save(d.get('steps') or ())
            if op == 'reset_plan': return r.reset_plan()
            raise ReleaseError(f'unknown release action: {op}')
        except Exception as e: return fail(e)

    @rt('/releases/tail')
    async def releases_tail(repo: str = '', lines: int = 80):
        "The end of the output as plain text -- for a summary, or for the agent to read."
        try: return {'text': await off_loop(release(repo).tail, lines)}
        except Exception as e: return fail(e)

    async def release_ws(sock):
        "One viewer of the pipeline terminal. Binary frames are keystrokes; text is control."
        await sock.accept()
        r = q = None
        try:
            hello = json.loads((await sock.receive()).get('text') or '{}')
            ctx.gate.check(hello.get('token'))     # the same boundary a pty always has
            r = release(hello.get('repo') or '')
            r.resize(int(hello.get('cols') or 100), int(hello.get('rows') or 30))
            q = r.subscribe()
        except Exception as e:
            await sock.send_text(json.dumps({'t': 'error', 'error': errstr(e)}))
            await sock.close()
            return

        async def to_browser():
            while True:
                data = await q.get()
                await sock.send_bytes(data)

        async def from_browser():
            while True:
                m = await sock.receive()
                if m['type'] == 'websocket.disconnect': return
                if (b := m.get('bytes')) is not None: r.write(b)
                elif (s := m.get('text')) is not None:
                    c = json.loads(s)
                    if c.get('t') == 'size': r.resize(c.get('cols', 100), c.get('rows', 30))

        send = asyncio.create_task(to_browser())
        recv = asyncio.create_task(from_browser())
        try:
            await asyncio.wait({send, recv}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            r.unsubscribe(q)
            for task in (send, recv):
                if not task.done(): task.cancel()
            try: await sock.close()
            except Exception: pass

    # A raw Starlette route, exactly as `/term/ws` is registered when the app is built.
    # FastHTML's own `ws` wrapper injects parameters by name and would hand this handler
    # `None` instead of the socket -- and a pty needs the socket, not a rendered response.
    app.router.routes.append(WebSocketRoute('/release/ws', release_ws))
