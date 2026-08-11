"""The release and deploy pipelines, and the one terminal they run on.

Both are `leela.pipelines.Pipeline`, so both are served from here rather than from two
blocks that would differ only in a noun. The state lives in this closure, one object per
project root and kind, because a pipeline is a *running thing*: the request that starts a
step and the websocket that shows its output have to be talking about the same pty, and a
per-request object could not be.

`/pipeline/ws` is a separate socket from `/term/ws` rather than a `kind` on it because the
pty is not opened by whoever attaches: the pipeline starts it, keeps pumping it whether or
not anyone is watching, and replays what has already scrolled by to each new viewer. A pty
nobody reads stops the child mid-write, and "the deploy hung because the panel was closed"
is the failure that arrangement exists to prevent.
"""

from __future__ import annotations

from ...core.web import fail, off_loop, pipeline_socket
from .deploys import Deploy
from ...core.envs import EnvStore
from .pipelines import PipelineError
from .releases import Release
from ..git.repos import RepoSet, repo_for

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
        op, target = str(d.get('op') or ''), d.get('repo') or ''
        p = pipeline(kind, target)
        if op == 'scaffold' and kind == 'deploy':
            out = await off_loop(p.scaffold, d.get('domain') or '', d.get('subdomain') or '',
                                 d.get('app') or '', bool(d.get('force')), d.get('second_host') or '')
            return out | {'state': state(kind, target)}
        if op == 'start': await p.start(d.get('step') or '', bool(d.get('auto', True)))
        elif op == 'step': await p.start(d.get('step') or '', False)
        elif op == 'stop': p.stop()
        elif op == 'skip': p.skip(d.get('step') or '')
        elif op == 'reset': p.reset()
        elif op == 'save': p.save(d.get('steps') or ())
        elif op == 'reset_plan': p.reset_plan()
        else: raise PipelineError(f'unknown {kind} action: {op}')
        return state(kind, target)

    def state(kind, target):
        """The pipeline's state, and on a failure, which package raised.

        Attribution is attached here rather than computed by the panel because it needs the
        workspace's checkouts to rewrite a `site-packages` path to the repository you can
        actually fix, and the workspace is what this block has.
        """
        p = pipeline(kind, target)
        out = p.state()
        if out.get('failed'):
            try: out['blame'] = p.blame([str(r) for r in RepoSet(ctx.fs.roots).paths()])
            except Exception: out['blame'] = {}
        return out

    @rt('/releases')
    def releases_info(repo: str = ''):
        try: return state('release', repo)
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
        try: return state('deploy', repo)
        except Exception as e: return fail(e)

    @rt('/deploys/action')
    async def deploys_action(req):
        try: return await act('deploy', await req.json())
        except Exception as e: return fail(e)

    @rt('/deploys/tail')
    async def deploys_tail(repo: str = '', lines: int = 80):
        try: return {'text': await off_loop(pipeline('deploy', repo).tail, lines)}
        except Exception as e: return fail(e)

    # One implementation, three kinds: `core.web.pipeline_socket` speaks the same protocol
    # as `/term/ws`, so the browser renders all of them with the same xterm component.
    pipeline_socket(app, '/pipeline/ws', ctx.gate,
                    lambda hello: pipeline(str(hello.get('kind') or 'release'),
                                           hello.get('repo') or hello.get('cwd') or ''))
