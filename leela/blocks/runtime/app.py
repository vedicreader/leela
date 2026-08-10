"""Which interpreter runs the code, and what is currently running in it.

Four related things live here because they are four views of one decision.

**The project runtime.** Leela stays in its own environment; user code belongs to the
folder's. So a conventional project venv is the default, discovered rather than configured,
and `/runtime/create` will make one — installing *only* the kernel transport into it, never
Leela itself. That is the whole reason this is not simply "run in my environment".

**Kernels.** `/kernel/select` restarts, and restarting loses the namespace. The client says
so before it posts rather than this route deciding on the user's behalf that it was
acceptable. Selecting also closes the shell terminal, because a shell cannot change its
inherited `VIRTUAL_ENV` after it starts — reopening is how it picks up the new one.

**Live envs.** A process appears in `/envs` only if it has an inspector *in* it. That is the
complete answer to "will you pick up the uvicorn I started in a terminal": not unless it
says `dhrishti.serving.serve()`, or Leela started it from a run configuration.

**Dev servers.** Started under that same inspector, which is what makes a running server's
module namespace watchable in the variable panel while it serves.

`ctx.docs.mark_all_stale()` is called after anything that resets a namespace. Saved outputs
stay useful but stop claiming to be fresh, which is the difference between a stale number
and a lie.
"""

from __future__ import annotations

import os
import shutil

from ... import errstr
from ...core.web import fail, off_loop

__all__ = ['CAPS', 'connect']

CAPS = ('fs', 'pool', 'dev', 'terms', 'tab', 'docs')


def connect(app, ctx):
    rt = app.route
    session = ctx.session

    # -- project runtime ---------------------------------------------------
    @rt('/runtime/broker')
    def runtime_broker():
        broker = getattr(ctx.pool, 'broker', None)
        return broker.status() if broker else {'live': len(ctx.pool.kernels), 'limit': None, 'runtimes': []}

    @rt('/runtime/info')
    async def runtime_info():
        from .kernels import project_python
        from .support import kernel_support
        root = ctx.fs.roots[0] if ctx.fs.roots else None
        py = project_python([root]) if root else None
        support = await off_loop(kernel_support, py) if py else {}
        return {'root': str(root or ''), 'python': py or '', 'needs_create': bool(root and not py),
                'needs_support': bool(py and not support.get('ipykernel', {}).get('available')),
                'support': support, 'active': ctx.pool.default_python or ''}

    @rt('/runtime/support')
    async def runtime_support(req):
        from .support import install_kernel_support
        d = await req.json()
        py = d.get('python') or ctx.pool.default_python
        if not py: return fail('choose a project interpreter first')
        try:
            # The selected launcher becomes available immediately; no Leela restart needed.
            return await off_loop(install_kernel_support, py)
        except Exception as e: return fail(f'could not install project kernel support — {errstr(e)}')

    @rt('/runtime/create')
    async def runtime_create():
        "Create an explicit .venv for the project and install only its kernel transport."
        if not ctx.fs.roots: return fail('open a folder first')
        target = ctx.fs.roots[0]/'.venv'
        if target.exists(): return fail(f'{target} already exists')

        def create():
            import subprocess
            import venv
            if uv := shutil.which('uv'):
                subprocess.run([uv, 'venv', str(target)], check=True, env=os.environ.copy())
            else: venv.EnvBuilder(with_pip=True).create(target)
            py = target/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
            from .support import install_kernel_support
            install_kernel_support(py)
            return str(py)

        try: py = await off_loop(create)
        except Exception as e: return fail(f'could not create .venv — {errstr(e)}')
        ctx.pool.choose(python=py)
        return {'ok': True, 'python': py}

    # -- kernels -----------------------------------------------------------
    @rt('/kernel/interrupt')
    async def k_interrupt():
        k = session.runtime_peek()
        if k is None: return fail('no running kernel')
        if hasattr(k, 'stop'): return await k.stop(timeout=2.0)
        await k.interrupt()
        return {'ok': True, 'forced': False, 'note': 'interrupt sent'}

    @rt('/kernel/restart')
    async def k_restart():
        k = session.runtime_peek()
        if k: await k.restart()
        ctx.docs.mark_all_stale()
        return {'ok': True, 'base': k.base if k else None}

    @rt('/kernel/info')
    async def k_info():
        from pathlib import Path
        k = await session.runtime()
        return {'alive': bool(k and k.alive), 'base': k.base if k else None,
                'pid': k.pid if k else None,
                'key': getattr(k, 'name', '') or Path(session.kernel_key()).name or 'kernel',
                'boot_error': k.boot_error if k else None,
                'api_error': getattr(k, 'last_api_error', '') if k else '',
                'cwd': str(session.cwd_for() or ''),
                'tabs': [{'running': t.running, 'dirty': t.dirty} for t in session.tabs]}

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
        k = await session.kernel(t)
        ctx.docs.mark_all_stale()
        session.save()
        return {'ok': True, 'cwd': str(session.cwd_for(t) or ''), 'base': k.base if k else None}

    @rt('/kernel/select')
    async def k_select(req):
        """Choose a launcher and/or an interpreter, and start the kernel on it.

        This restarts, and restarting loses the namespace -- so the client says so before
        it posts, rather than this route deciding on the user's behalf that it was fine.
        """
        d = await req.json()
        try:
            o = await session.set_kernel(kind=d.get('kind'),
                                         python=d['python'] if 'python' in d else False,
                                         private=d.get('private'))
            # A shell cannot change its inherited VIRTUAL_ENV after it starts. Closing it
            # lets the client reopen immediately with the newly selected project runtime.
            ctx.terms.close('shell')
            ctx.docs.mark_all_stale()
        except Exception as e: return fail(e)
        return {'ok': True, **o}

    # -- live envs ---------------------------------------------------------
    @rt('/envs')
    def envs_route():
        """Everything the variable panel could point at, and what it is pointing at now.

        A process only appears here if it has an inspector in it. That is the whole answer
        to "will you pick up the uvicorn I started in a terminal": not unless it says
        `dhrishti.serving.serve()`, or leela started it from a run configuration.
        """
        return {'envs': session.envs(), 'watching': session.env_base,
                'hint': 'import dhrishti.serving as ds; ds.serve(name="api")'}

    @rt('/envs/watch')
    async def envs_watch(req):
        d = await req.json()
        return {'ok': True, 'watching': session.watch_env(d.get('base'))}

    # -- dev servers -------------------------------------------------------
    @rt('/dev/list')
    def dev_list(): return {'servers': [s.state() for s in ctx.dev.all()]}

    @rt('/dev/start')
    async def dev_start(path: str = '', name: str = ''):
        """Start a run configuration, or a file, under a live inspector.

        The inspector is in the process the command runs in -- that is what makes its
        module namespace watchable while it serves. `name` picks a configuration; `path`
        runs a file directly.
        """
        try:
            s = await session.run(name or path)
            return {'ok': s.alive, **s.state(), 'log': s.tail(20)}
        except Exception as e: return fail(e)

    @rt('/dev/stop')
    async def dev_stop(path: str):
        await ctx.dev.stop(path)
        return {'ok': True}

    @rt('/dev/log')
    def dev_log(path: str, n: int = 60):
        s = ctx.dev.get(path)
        return {'log': s.tail(n) if s else [], **(s.state() if s else {})}
