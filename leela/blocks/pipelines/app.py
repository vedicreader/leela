"""The release and deploy pipelines, and the one terminal they run on.

Both are `leela.pipelines.Pipeline`, so both are served from here rather than from two
blocks that would differ only in a noun. The state lives in this closure, one object per
project root and kind, because a pipeline is a *running thing*: the request that starts a
step and the websocket that shows its output have to be talking about the same pty, and a
per-request object could not be.

`/pipeline/ws` speaks the same protocol as `/term/ws` -- a JSON hello carrying the terminal
token, then raw bytes both ways -- so the browser renders it with the same xterm component,
in the same theme, with the same keyboard. It is a separate socket rather than a `kind` on
the existing one because the pty is not opened by whoever attaches: the pipeline starts it,
keeps pumping it whether or not anyone is watching, and replays what has already scrolled by
to each new viewer. A pty nobody reads stops the child mid-write, and "the deploy hung
because the panel was closed" is the failure this arrangement exists to prevent.
"""

from __future__ import annotations

import asyncio
import json

from starlette.routing import WebSocketRoute

from ... import errstr
from ...core.web import fail, off_loop
from ...deploys import Deploy
from ...envs import EnvStore
from ...pipelines import PipelineError
from ...releases import Release
from ...repos import repo_for

__all__ = ['CAPS', 'connect']

CAPS = ('fs', 'gate')

KINDS = {'release': Release, 'deploy': Deploy}


def connect(app, ctx):
    rt = app.route
    live = {}

    def pipeline(kind, target=''):
        "The pipeline for one project and kind, made once and then kept -- it has a process in it."
        root = repo_for(ctx.session, target)
        key = (kind, str(root))
        if key not in live:
            live[key] = KINDS[kind](root, env=EnvStore())
        # The interpreter can change after the pipeline was made -- picking a project venv
        # in the kernel picker must retarget the next step, not the next restart.
        live[key].python = ctx.session.pool.default_python
        return live[key]

    async def act(kind, d):
        """One explicit move: start, retry a step, skip it, stop, forget, or edit the plan.

        `start` returns as soon as the first step is *running*, not when the pipeline
        finishes. The state it returns says which step that is, and the terminal says the
        rest -- a deploy that took four minutes must not be a four-minute request.
        """
        op = str(d.get('op') or '')
        p = pipeline(kind, d.get('repo') or '')
        if op == 'start': return await p.start(d.get('step') or '', bool(d.get('auto', True)))
        if op == 'step': return await p.start(d.get('step') or '', False)
        if op == 'stop': return p.stop()
        if op == 'skip': return p.skip(d.get('step') or '')
        if op == 'reset': return p.reset()
        if op == 'save': return p.save(d.get('steps') or ())
        if op == 'reset_plan': return p.reset_plan()
        if op == 'scaffold' and kind == 'deploy':
            return await off_loop(p.scaffold, d.get('domain') or '', d.get('subdomain') or '',
                                  d.get('app') or '', bool(d.get('force')))
        raise PipelineError(f'unknown {kind} action: {op}')

    @rt('/releases')
    def releases_info(repo: str = ''):
        try: return pipeline('release', repo).state()
        except Exception as e: return fail(e)

    @rt('/releases/action')
    async def releases_action(req):
        try: return await act('release', await req.json())
        except Exception as e: return fail(e)

    @rt('/releases/tail')
    async def releases_tail(repo: str = '', lines: int = 80):
        "The end of the output as plain text -- for a summary, or for the agent to read."
        try: return {'text': await off_loop(pipeline('release', repo).tail, lines)}
        except Exception as e: return fail(e)

    @rt('/deploys')
    def deploys_info(repo: str = ''):
        try: return pipeline('deploy', repo).state()
        except Exception as e: return fail(e)

    @rt('/deploys/action')
    async def deploys_action(req):
        try: return await act('deploy', await req.json())
        except Exception as e: return fail(e)

    @rt('/deploys/tail')
    async def deploys_tail(repo: str = '', lines: int = 80):
        try: return {'text': await off_loop(pipeline('deploy', repo).tail, lines)}
        except Exception as e: return fail(e)

    async def pipeline_ws(sock):
        "One viewer of a pipeline terminal. Binary frames are keystrokes; text is control."
        await sock.accept()
        p = q = None
        try:
            hello = json.loads((await sock.receive()).get('text') or '{}')
            ctx.gate.check(hello.get('token'))     # the same boundary a pty always has
            kind = str(hello.get('kind') or 'release')
            if kind not in KINDS: raise PipelineError(f'unknown pipeline: {kind}')
            # `cwd` is what the terminal component sends; for these it is the project root.
            p = pipeline(kind, hello.get('repo') or hello.get('cwd') or '')
            p.resize(int(hello.get('cols') or 100), int(hello.get('rows') or 30))
            q = p.subscribe()
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
                if (b := m.get('bytes')) is not None: p.write(b)
                elif (s := m.get('text')) is not None:
                    c = json.loads(s)
                    if c.get('t') == 'size': p.resize(c.get('cols', 100), c.get('rows', 30))

        send = asyncio.create_task(to_browser())
        recv = asyncio.create_task(from_browser())
        try:
            await asyncio.wait({send, recv}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            p.unsubscribe(q)
            for task in (send, recv):
                if not task.done(): task.cancel()
            try: await sock.close()
            except Exception: pass

    # A raw Starlette route, exactly as `/term/ws` is registered when the app is built.
    # FastHTML's own `ws` wrapper injects parameters by name and would hand this handler
    # `None` instead of the socket -- and a pty needs the socket, not a rendered response.
    app.router.routes.append(WebSocketRoute('/pipeline/ws', pipeline_ws))
