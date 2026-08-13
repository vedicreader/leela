"""The release and deploy pipelines, and the one terminal they run on.

Both are a `Pipeline`, so both are served from here. The state lives in this closure, one object
per project root and kind, because the request that starts a step and the websocket that shows
its output have to be talking about the same pty. `/pipeline/ws` is separate from `/term/ws`
because the pipeline, not the viewer, opens the pty and keeps pumping it: a pty nobody reads
stops the child mid-write.
"""

from __future__ import annotations

from fastcore.basics import first

from ...core.web import fail, off_loop, pipeline_socket
from ..runtime.kernels import python_for
from .deploys import Deploy
from ...core.envs import EnvStore
from .pipelines import PipelineError, resolve_script
from .releases import Release
from ..git.repos import RepoSet, repo_for

__all__ = ['CAPS', 'connect']

CAPS = ('fs', 'gate')

KINDS = {'release': Release, 'deploy': Deploy}


def nbdev_prepare(session, target=''):
    "nbdev's prepare, run in the folder that owns `settings.ini` and in that folder's venv."
    import configparser, subprocess
    if not session.fs.roots: raise PipelineError('open a folder first')
    root = repo_for(session, target)
    settings = first(r/'settings.ini' for r in (root, *session.fs.roots) if (r/'settings.ini').exists())
    if settings is None: raise PipelineError('no settings.ini in any open folder — not an nbdev project')
    root = settings.parent
    argv = resolve_script(['nbdev_prepare'], python_for(root, session))
    # `resolve_script` hands back what it was given when neither spelling exists anywhere.
    if argv[0] == 'nbdev_prepare': raise PipelineError(f'nbdev is not installed in {root.name}')
    r = subprocess.run(argv, cwd=str(root), capture_output=True, text=True, timeout=900)
    if r.returncode: raise PipelineError((r.stderr or r.stdout or 'nbdev prepare failed').strip()[-4000:])
    d = configparser.ConfigParser(); d.read(settings)
    defaults = d.defaults()
    return dict(ok=True, root=str(root), nbs_path=defaults.get('nbs_path', 'nbs'),
        lib_path=defaults.get('lib_path', defaults.get('lib_name', '')),
        log=(r.stdout or '')[-2000:])


def connect(app, ctx):
    rt = app.route
    live = {}

    def pipeline(kind, target=''):
        "The pipeline for one project and kind, made once and then kept -- it has a process in it."
        root = repo_for(ctx.session, target)
        key = (kind, str(root))
        if key not in live: live[key] = KINDS[kind](root, env=EnvStore())
        # Re-resolved every time from `root`, not from `pool.default_python`: a workspace holds
        # several checkouts, and a release must run the *project's* console scripts.
        live[key].python = python_for(root, ctx.session)
        return live[key]

    async def act(kind, d):
        "One explicit move: start, retry a step, skip it, stop, forget, or edit the plan."
        # `start` returns as soon as the first step is running, not when the pipeline finishes.
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
        "The pipeline's state, and on a failure, which package raised."
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
        "The end of the output as plain text."
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

    @rt('/project/nbdev_prepare')
    async def project_nbdev_prepare(repo: str = ''):
        "Run nbdev's prepare in the project that owns `settings.ini`, in that project's venv."
        try: return await off_loop(nbdev_prepare, ctx.session, repo)
        except Exception as e: return fail(e)

    # `pipeline_socket` speaks the same protocol as `/term/ws`, so the browser renders both
    # with the same xterm component.
    pipeline_socket(app, '/pipeline/ws', ctx.gate,
        lambda hello: pipeline(str(hello.get('kind') or 'release'),
            hello.get('repo') or hello.get('cwd') or ''))
