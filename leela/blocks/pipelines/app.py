"The release and deploy pipelines, and the one terminal they run on."

from __future__ import annotations

from fastcore.basics import first
from starlette.responses import JSONResponse
from fastcore.xtras import Path

from ...core.web import fail, off_loop, pipeline_socket
from ..runtime.kernels import python_for, venv_env
from .deploys import Deploy
from ...core.envs import EnvStore
from pullup.pipeline import resolve_script, uv_argv
from pullup.project import app_project, nbdev_project, release_flow
from .pipelines import PipelineError, Release, step_python
from ..git.repos import RepoSet, repo_for

__all__ = ['CAPS', 'connect', 'FASTSHIP_OPS', 'fastship_state', 'fastship_run', 'fastship_new']

CAPS = ('fs', 'gate')

KINDS = {'release': Release, 'deploy': Deploy}

def nbdev_config(root):
    "The nbdev config for `root`, or None. Whichever of the two files the project keeps."
    if not nbdev_project(root): return None
    from nbdev.config import get_config
    try: return get_config(str(root), also_settings=True)
    except Exception: return None

def nbdev_prepare(session, target=''):
    "nbdev's prepare, run in the folder that owns its config and in that folder's venv."
    import subprocess
    if not session.fs.roots: raise PipelineError('open a folder first')
    cfg = first(c for r in (repo_for(session, target), *session.fs.roots) if (c := nbdev_config(r)))
    if cfg is None: raise PipelineError(
        'no settings.ini and no [tool.nbdev] in any open folder, so this is not an nbdev project')
    root = Path(cfg.config_path)
    argv = uv_argv(root, ['nbdev-prepare']) or resolve_script(['nbdev-prepare'], step_python(session, root))
    if argv[0] == 'nbdev-prepare': raise PipelineError(
        f'no nbdev-prepare in {root.name}: nbdev is not installed in the environment it uses')
    # Through `venv_env`, like the pty steps: a child that keeps the bundle's `PYTHONPATH` imports
    # its standard library, and `nbdev-test` died inside `linecache` before reporting a notebook.
    r = subprocess.run(argv, cwd=str(root), stdin=subprocess.DEVNULL, start_new_session=True, capture_output=True, text=True, timeout=900,
                       env=venv_env(python_for(root, session)))
    if r.returncode: raise PipelineError((r.stderr or r.stdout or 'nbdev prepare failed').strip()[-4000:])
    return dict(ok=True, root=str(root), nbs_path=Path(cfg.nbs_path).name,
        lib_path=Path(cfg.lib_path).name, log=(r.stdout or '')[-2000:])

FASTSHIP_OPS = {
    'changelog': ('ship-changelog', 'Rewrite CHANGELOG.md from the issues closed since the last release.'),
    'bump': ('ship-bump', 'Raise the version. fastship bumps after releasing, not before.'),
    'pages': ('ship-pages', 'Enable GitHub Pages from main and use its URL as the homepage.'),
}

def _ship(root, session, argv, timeout=900):
    "One `ship-*` command, in `root` and in `root`'s venv."
    import subprocess
    resolved = resolve_script(argv, python := step_python(session, root))
    if resolved[0] == argv[0]:
        raise PipelineError(f'fastship is not installed in {root.name}. Add it to the dev dependencies')
    r = subprocess.run(resolved, cwd=str(root), stdin=subprocess.DEVNULL, start_new_session=True, capture_output=True, text=True, timeout=timeout,
                       env=venv_env(python))
    if r.returncode: raise PipelineError((r.stderr or r.stdout or f'{argv[0]} failed').strip()[-4000:])
    return (r.stdout or '')[-2000:]

def fastship_state(session, target=''):
    "What fastship makes of this project: its flow, whether it is installed, and what it would need."
    if not session.fs.roots: raise PipelineError('open a folder first')
    root = repo_for(session, target)
    flow = release_flow(root)
    installed = resolve_script(['ship-bump'], python_for(root, session))[0] != 'ship-bump'
    return dict(ok=True, root=str(root), flow=flow, nbdev=flow == 'nbdev', app=app_project(root),
        installed=installed, changelog=(root/'CHANGELOG.md').exists(),
        ops=[{'op': k, 'cmd': c, 'doc': doc} for k, (c, doc) in FASTSHIP_OPS.items()],
        why='' if installed else f'fastship is not installed in {root.name}. Add it to the dev dependencies')

def fastship_run(session, op, target='', part=None):
    "One fastship command, in the project the panel is about and in that project's venv."
    if op not in FASTSHIP_OPS: raise PipelineError(f'unknown fastship action: {op}')
    if not session.fs.roots: raise PipelineError('open a folder first')
    root = repo_for(session, target)
    cmd, doc = FASTSHIP_OPS[op]
    argv = [cmd, *(['--part', str(int(part))] if op == 'bump' and part not in (None, '') else [])]
    return dict(ok=True, root=str(root), op=op, doc=doc, log=_ship(root, session, argv))

def fastship_new(session, name, target='', description='A Python package'):
    "A new fastship package beside the project the panel is about, scaffolded by gheasy."
    from ..workflows.workflows import gheasy_core
    core = gheasy_core()
    slug = str(name or '').strip()
    if not slug or slug.startswith('.') or {'/', '\\'} & set(slug):
        raise PipelineError(f'not a package name: {name}')
    root = repo_for(session, target).parent/slug
    if root.exists(): raise PipelineError(f'{root} already exists')
    root.mkdir(parents=True)
    try:
        core.gh_fastship_new(str(root), description=description or 'A Python package')
        core.gh_fastship_release(path=str(root))
    except Exception:
        # Retrying must not meet the folder this attempt made. A half-written tree is left to look at.
        if not any(root.iterdir()): root.rmdir()
        raise
    return dict(ok=True, root=str(root), name=slug)

def connect(app, ctx):
    rt = app.route
    live = {}
    def pipeline(kind, target='', make=False):
        "The pipeline for one project and kind, made once and then kept: it has a process in it. `make` refuses a Python project with no venv and no pyproject.toml."
        root = repo_for(ctx.session, target)
        key = (kind, str(root))
        if key not in live: live[key] = KINDS[kind](root, env=EnvStore())
        live[key].python = step_python(ctx.session, root, make)
        return live[key]
    async def act(kind, d):
        "One explicit move: start, retry a step, skip it, stop, forget, or edit the plan."
        op, target = str(d.get('op') or ''), d.get('repo') or ''
        p = await off_loop(pipeline, kind, target, op in ('start', 'step'))
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
    @rt('/project/fastship')
    async def project_fastship(repo: str = ''):
        "What fastship makes of this project. The non-nbdev half of the same front end."
        try: return await off_loop(fastship_state, ctx.session, repo)
        except Exception as e: return fail(e)
    @rt('/project/fastship/action')
    async def project_fastship_action(req):
        "One fastship command, or a new package. Every failure comes back the same shape."
        try:
            d = await req.json()
            op, repo = str(d.get('op') or ''), d.get('repo') or ''
            if op == 'new':
                from ...hub import admit_folder, window_name
                made = await off_loop(fastship_new, ctx.session, d.get('name') or '', repo, d.get('description') or 'A Python package')
                if no := await off_loop(admit_folder, made['root'], window_name(ctx.session), covers=ctx.session.fs.covers, headers=req.headers):
                    return JSONResponse({**no[1], 'root': made['root'], 'name': made['name'], 'error': f"{no[1]['error']} The package is at {made['root']}."}, status_code=no[0])
                ctx.session.fs.add_root(made['root'])
                return made
            return await off_loop(fastship_run, ctx.session, op, repo, d.get('part'))
        except Exception as e: return fail(e)
    pipeline_socket(app, '/pipeline/ws', ctx.gate,
        lambda hello: pipeline(str(hello.get('kind') or 'release'),
            hello.get('repo') or hello.get('cwd') or ''))
