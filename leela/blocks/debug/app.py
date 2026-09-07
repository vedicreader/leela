"The direct debugpy session as routes: launch, stream, inspect, step, stop."

from __future__ import annotations
from kunda.pythons import clean_env

import shutil, subprocess, sys
from pathlib import Path

from fasthtml.common import StreamingResponse

from ... import errstr
from ...core.web import fail, off_loop, sse
from .debug import frame_path, open_path

__all__ = ['CAPS', 'connect']

CAPS = ('fs', 'tab', 'runs', 'debug')

def state_ui(session_fs, state):
    "Mark each frame with the workspace file it can be opened from, or nothing."
    for frame in state.get('frames', []): frame['open_path'] = open_path(session_fs, frame_path(frame))
    return state

def connect(app, ctx):
    rt = app.route
    ws, state = ctx.session, ctx.debug
    def ui(s): return state_ui(ctx.fs, s)
    def active(): return state.direct_session
    @rt('/debug/capabilities')
    def debug_capabilities():
        from .debug import debugpy_available
        from ..runtime.kernels import python_for, _runtime_python
        # `_runtime_python` and not `sys.executable`: in the bundle that name is Leela itself,
        # so probing it for debugpy relaunches the app.
        python = python_for(ws.cwd_for(), ws) or _runtime_python()
        return {'python': str(python), 'debugpy': debugpy_available(python),
                'notebook': True, 'direct': debugpy_available(python)}
    @rt('/debug/install')
    async def debug_install(req):
        from ..runtime.kernels import python_for
        d = await req.json(); python = d.get('python') or python_for(ws.cwd_for(), ws)
        if not python: return fail('choose a project interpreter first')
        def install():
            uv = shutil.which('uv')
            cmd = ([uv, 'pip', 'install', '--python', str(python), 'debugpy'] if uv else
                   [str(python), '-m', 'pip', 'install', 'debugpy'])
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180, env=clean_env())
            if result.returncode: raise RuntimeError(result.stderr or result.stdout)
        try: await off_loop(install); return {'ok': True, 'python': str(python)}
        except Exception as e: return fail(e)
    @rt('/debug/start')
    async def debug_start(req):
        "Launch a Python file/module or attach through a direct debugpy DAP session."
        from .debug import DebugSession
        from ..runtime.kernels import python_for, _runtime_python
        d = await req.json(); name = d.get('name') or ''
        run = ctx.runs.get(name) if name else None
        config = run.dict() if run else dict(d)
        from kunda.support import work_dir
        root = ws.project_repo or Path(work_dir())
        cwd = config.get('cwd') or str(root)
        if cwd and not Path(cwd).is_absolute(): cwd = str((root/str(cwd)).resolve())
        # Resolved after `cwd`, so the debugger uses the venv of whatever is being debugged.
        python = d.get('python') or python_for(cwd, ws) or _runtime_python()
        program = config.get('program') or (ctx.tab.path if ctx.tab and (ctx.tab.path or '').endswith('.py') else '')
        if program and not Path(program).is_absolute(): program = str((root/program).resolve())
        config.update(program=program, cwd=cwd, justMyCode=config.get('justMyCode', True),
                      stopOnEntry=config.get('stopOnEntry', False), subProcess=config.get('subProcess', True),
                      breakOnRaised=config.get('breakOnRaised', False), breakOnUncaught=config.get('breakOnUncaught', True))
        if not config.get('program') and not config.get('module') and config.get('request', 'launch') == 'launch':
            return fail('open a Python file or set program/module in the run configuration')
        if previous := active(): await off_loop(previous.disconnect)
        session = DebugSession(python, cwd)
        breakpoints = d.get('breakpoints') or ({program: d.get('lines') or []} if program else {})
        try:
            await off_loop(session.start_adapter)
            await off_loop(session.launch, config, breakpoints)
        except Exception as e:
            await off_loop(session.disconnect)
            return fail(e)
        state.direct_session = session
        state.direct_name = config.get('name') or Path(program or config.get('module', 'python')).name
        return {'ok': True, 'name': state.direct_name, 'python': str(python)}
    @rt('/debug/events')
    async def debug_events(req):
        "Stream direct DAP output, stops, continuation, exit, and errors."
        session = active()
        if session is None: return fail('no direct debugger is active')
        async def events():
            while session.alive or not session.events.empty():
                if await req.is_disconnected(): break
                try: event = await off_loop(session.events.get, True, .25)
                except Exception: continue
                name, body = event.get('event'), event.get('body') or {}
                if name == 'stopped':
                    try: body = ui(await off_loop(session.state, body.get('threadId')))
                    except Exception as e: body = {'message': errstr(e)}; name = 'error'
                yield sse(name or 'event', body)
                if name in ('terminated', 'exited'): break
        return StreamingResponse(events(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
    @rt('/debug/state')
    async def debug_state(frame_id: int = 0):
        session = active()
        if session is None: return fail('no direct debugger is active')
        try: return ui(await off_loop(session.state, None, frame_id or None))
        except Exception as e: return fail(e)
    @rt('/debug/variables')
    async def debug_variables(reference: int):
        session = active()
        if session is None: return fail('no direct debugger is active')
        try: return {'variables': await off_loop(session.variables, reference)}
        except Exception as e: return fail(e)
    @rt('/debug/evaluate')
    async def debug_evaluate(req):
        session = active(); d = await req.json()
        if session is None: return fail('no direct debugger is active')
        try: return await off_loop(session.evaluate, d.get('expression', ''), d.get('frame_id'))
        except Exception as e: return fail(e)
    @rt('/debug/control')
    async def debug_control(req):
        session = active(); d = await req.json()
        if session is None: return fail('no direct debugger is active')
        try: return {'ok': True, **(await off_loop(session.control, d.get('command')))}
        except Exception as e: return fail(e)
    @rt('/debug/breakpoints')
    async def debug_breakpoints(req):
        session = active(); d = await req.json()
        if session is None: return fail('no direct debugger is active')
        try: return {'ok': True, 'breakpoints': await off_loop(session.set_breakpoints, d.get('path'),
                                                               d.get('breakpoints') or [])}
        except Exception as e: return fail(e)
    @rt('/debug/stop')
    async def debug_stop_direct():
        if session := active(): await off_loop(session.disconnect)
        state.clear_direct()
        return {'ok': True}
