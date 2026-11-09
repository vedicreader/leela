"Routes for the project runtime, its kernels, the live envs, and the dev servers."

from __future__ import annotations

import shutil
from pathlib import Path

from ... import errstr
from ...core.web import fail, json_obj, off_loop, pipeline_socket
from kunda.support import INSPECTOR

__all__ = ['CAPS', 'connect']

CAPS = ('fs', 'pool', 'terms', 'dev', 'tab', 'runs', 'docs', 'gate')

def copy_folder(root) -> bool:
    "Whether `root` is a walk folder of abhyasa's learning copies (`.../walks/<walk id>/`)."
    try: from abhyasa.contract import COPY_DIR, copy_home
    except ImportError: return False
    root = Path(root)
    return root.parent.name == COPY_DIR and any(copy_home(f) for f in root.glob('*.ipynb'))

def connect(app, ctx):
    rt = app.route
    session = ctx.session
    def active():
        "The interpreter the tab in front runs on: the chosen one, else its project's venv."
        from .kernels import python_for
        return python_for(session.cwd_for(), session)
    @rt('/runtime/broker')
    def runtime_broker():
        from .engines import engine_broker
        broker = getattr(ctx.pool, 'broker', None)
        out = (broker.status() if broker else
               {'live': len(ctx.pool.kernels), 'limit': None, 'runtimes': []})
        return {**out, 'models': engine_broker().status(),   # weights, alongside namespaces
                'auto_manage': bool(getattr(broker, 'auto_manage', False)),
                'idle': ctx.pool.idle}
    @rt('/runtime/engines/clear')
    async def runtime_engines_clear(req):
        "Release the loaded model weights. A model a session is using answers 409 until `force` is set."
        from .engines import engine_broker
        d = await req.json()
        broker = engine_broker()
        held = [e for e in broker.status()['engines'] if e['in_use']]
        if held and not d.get('force'):
            names = ', '.join(f"{e['runtime']}/{e['model']}" for e in held)
            return fail(f'a session is using {names}; force the clear to close it anyway', 409)
        freed = broker.close() if d.get('force') else broker.drop()
        return {'ok': True, 'freed': freed, 'live': broker.status()['live'],
                'note': (f'released {len(freed)} model ' + ('engine' if len(freed) == 1 else 'engines')
                         if freed else 'no model weights were loaded')}
    @rt('/runtime/close')
    async def runtime_close(req):
        "Close one runtime by key. The limit dialog answers with the key it was offered."
        d = await req.json()
        if not (key := str(d.get('key') or '')): return fail('key is required')
        broker = getattr(ctx.pool, 'broker', None)
        for p in (broker.pools if broker else [ctx.pool]):   # the offer can name another workspace's kernel
            if key not in p.kernels: continue
            if p.kernels[key].busy: return fail('that runtime is running a cell')
            await p.close(key)
            return {'ok': True, 'key': key}
        return fail('no runtime with that key')
    @rt('/runtime/auto-manage')
    async def runtime_auto_manage(req):
        "Whether leela closes the stalest idle kernel at the ceiling instead of asking."
        d = await req.json(); enabled = d.get('enabled')
        if not isinstance(enabled, bool): return fail('enabled must be true or false')
        broker = getattr(ctx.pool, 'broker', None)
        if broker is None: return fail('no kernel broker is registered')
        broker.auto_manage = enabled
        session.kernels_auto_manage = enabled; session.save()
        return {'ok': True, 'enabled': enabled,
                'note': ('leela closes the longest-idle runtime to make room'
                         if enabled else 'leela asks before closing a runtime')}
    @rt('/runtime/info')
    async def runtime_info():
        "Whether this project has an interpreter Leela can run cells with."
        from ..agent.models import probed
        from .kernels import project_python
        from kunda.support import inspector_support, installable, kernel_support
        # The checkout in hand, not the folder that holds it: a panel offering to create an
        # environment has to offer it where the work is, and name the one already there.
        root = session.project_repo
        if root and copy_folder(root): root = None   # a folder of abhyasa's learning copies is never a project: the copy runs in the learner's project
        py = project_python([root]) if root else None
        support = await off_loop(lambda: probed(f'support:{py}', lambda: kernel_support(py))) if py else {}
        # Its own cache, not `probed`: an install has to be able to drop this one answer, and
        # `forget_probes` drops every probe on the machine.
        inspector = await off_loop(inspector_support, py) if py else {}
        notice = support.get('ipykernel', {}).get('notice')
        return {'root': str(root or ''), 'python': py or '', 'needs_create': bool(root and not py),
            'needs_support': bool(py and not support.get('ipykernel', {}).get('available')),
            'notice': notice, 'needs_upgrade': bool(notice and installable(py)),
            'support': support, 'active': active() or '',
            'inspector': inspector, 'inspector_packages': list(INSPECTOR),
            'needs_inspector': bool(py and installable(py) and not inspector.get('available')),
            'uv': bool(shutil.which('uv'))}
    @rt('/runtime/support')
    async def runtime_support(req):
        "Install kernel support into a project interpreter; a lesson's tool environment is installed again through `make_tool_env`."
        from kunda.support import install_kernel_support
        from ..learn.toolenv import tool_of, upgrade_tool_env
        d = await req.json()
        py = d.get('python') or active()
        if not py: return fail('choose a project interpreter first')
        if key := tool_of(py):
            r = await off_loop(upgrade_tool_env, key)
            return {'ok': True, 'python': r.python} if r.ok else fail(f'could not install the lesson kernel again: {r.error}')
        try: return await off_loop(install_kernel_support, py)
        except Exception as e: return fail(f'could not install project kernel support: {errstr(e)}')
    @rt('/runtime/inspector')
    async def runtime_inspector(req):
        "Give a project environment its own copy of what the live-variable inspector imports."
        from kunda.support import install_inspector_support, installable
        d = await req.json()
        py = d.get('python') or active()
        if not py: return fail('choose a project interpreter first')
        if not installable(py):
            return fail('that is leela’s own interpreter; choose a project environment first')
        try: return await off_loop(install_inspector_support, py)
        except Exception as e: return fail(f'could not install the inspector’s packages: {errstr(e)}')
    @rt('/runtime/create')
    async def runtime_create(req):
        "Create a .venv in the project the person named, else the checkout in hand, and install only its kernel transport, never Leela itself."
        d = await json_obj(req) or {}
        root = session.project_repo
        if d.get('root'):
            try: root = Path(session.fs._check(d['root'], must_exist=True))
            except Exception as e: return fail(e)
        if root is None: return fail('open a folder first')
        if copy_folder(root): return fail('this folder holds learning copies from abhyasa; each copy runs in the environment of its own project')
        if d.get('root') and (root := session.venv_project(root)) is None: return fail('a loose file has no project to set up a .venv in')
        try: py, note = await off_loop(session.setup_venv, root)
        except Exception as e: return fail(f'could not create .venv: {errstr(e)}')
        return {'ok': True, 'python': py, 'root': str(root), 'note': note}
    @rt('/kernel/interrupt')
    async def k_interrupt():
        k = session.runtime_peek()
        busy = any(getattr(t, 'running', 0) for t in session.tabs)
        if k is None or not busy:
            # no cell executing: the toolbar's stop ends the runs still up, inspector included; an idle kernel has nothing to interrupt
            live = [s for s in ctx.dev.all() if s.alive]
            if live:
                for s in live: await ctx.dev.stop(s.script)
                return {'ok': True, 'forced': False, 'note': 'stopped ' + ', '.join(s.label or s.script for s in live)}
            if k is None: return fail('nothing running: no kernel and no run')
        if hasattr(k, 'stop'): return await k.stop(timeout=2.0)
        await k.interrupt()
        return {'ok': True, 'forced': False, 'note': 'interrupt sent'}
    @rt('/kernel/restart')
    async def k_restart(): return await session.restart_kernel()
    @rt('/kernel/info')
    async def k_info():
        "What the kernel pill shows. Never starts one: it reports that there is none."
        k = session.runtime_peek()
        evicted = getattr(k, 'evicted', None)
        if k is not None: k.evicted = None
        return {'alive': bool(k and k.alive), 'base': k.base if k else None,
            'pid': k.pid if k else None,
            'key': session.runtime_label(k=k),
            'boot_error': k.boot_error if k else None,
            'api_error': getattr(k, 'last_api_error', '') if k else '',
            'notice': getattr(k, 'notice', None),
            'cwd': str(session.cwd_for() or ''),
            'tabs': [{'running': t.running, 'dirty': t.dirty} for t in session.tabs],
            **({'evicted': evicted} if evicted else {}), 'no_venv': session.venv_notice()}
    @rt('/kernel/options')
    def k_options():
        "What the kernel picker shows: the launchers, the interpreters, and what is running."
        return session.kernel_options()
    @rt('/kernel/cwd')
    async def k_cwd(req):
        "Set this tab's working directory and restart its kernel so the process adopts it."
        d = await req.json()
        t = ctx.tab
        if t is None: return fail('no active tab')
        raw = (d.get('cwd') or '').strip()
        try:
            cwd = ctx.fs._check(raw, must_exist=True) if raw else None
            if cwd is not None and not cwd.is_dir(): return fail(f'{cwd} is not a directory')
        except Exception as e: return fail(e)
        key = session.kernel_key(t)
        session.watch_env(None)
        t.cwd = str(cwd) if cwd else ''
        await ctx.pool.close(key)
        from .kernels import KernelLimit
        try: k = await session.kernel(t)
        except KernelLimit as e: return fail(e)
        ctx.docs.mark_all_stale()
        session.save()
        return {'ok': True, 'cwd': str(session.cwd_for(t) or ''), 'base': k.base if k else None}
    @rt('/kernel/select')
    async def k_select(req):
        "Choose a launcher and/or an interpreter, and start the kernel on it."
        d = await req.json()
        try:
            o = await session.set_kernel(kind=d.get('kind'),
                python=d['python'] if 'python' in d else False,
                private=d.get('private'))
            ctx.terms.close('shell')
            ctx.docs.mark_all_stale()
        except Exception as e: return fail(e)
        return {'ok': True, **o}
    @rt('/envs')
    def envs_route():
        "Everything the variable panel could point at. A process appears once it has an inspector in it."
        return {'envs': session.envs(), 'watching': session.env_base,
            'hint': 'import dhrishti.serving as ds; ds.serve(name="api")'}
    @rt('/envs/watch')
    async def envs_watch(req):
        d = await req.json()
        return {'ok': True, 'watching': session.watch_env(d.get('base'))}
    @rt('/dev/list')
    def dev_list(): return {'servers': [s.state() for s in ctx.dev.all()]}
    @rt('/dev/start', methods=['POST'])
    async def dev_start(path: str = '', name: str = ''):
        "Start a run configuration (`name`) or a file (`path`) under a live inspector."
        # The picker's unsaved configuration for the open file carries a name no saved configuration
        # matches, and `run` would read that name as the path of `main` rather than `main.py`.
        try:
            s = await session.run(name if ctx.runs.get(name) else (path or name))
            return {'ok': s.alive, **s.state(), 'log': s.tail(20)}
        except Exception as e: return fail(e)
    @rt('/dev/stop', methods=['POST'])
    async def dev_stop(path: str):
        await ctx.dev.stop(path)
        return {'ok': True}
    @rt('/dev/log')
    def dev_log(path: str, n: int = 60):
        s = ctx.dev.get(path)
        return {'log': s.tail(n) if s else [], **(s.state() if s else {})}
    def _run_pty(hello):
        "Which run a terminal is attaching to. The client sends it in the `cwd` field."
        s = ctx.dev.get(hello.get('path') or hello.get('cwd') or '')
        if s is None: raise LookupError('that run is not running')
        return s
    pipeline_socket(app, '/run/ws', ctx.gate, _run_pty)
