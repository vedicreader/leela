"Managed ipykernels: execution over the shell channel, inspection over HTTP to an in-kernel."

from __future__ import annotations
import asyncio, importlib.util, os, subprocess, sys, queue, shutil, tempfile, time, uuid, warnings
from dataclasses import dataclass, field
from pathlib import Path
from fastcore.all import store_attr, ifnone, first, L
from fastcore.ansi import strip_ansi
from jupyter_client.manager import AsyncKernelManager
from jupyter_client.kernelspec import KernelSpec

from ...core.inspectors import reg_dir, active

from .support import LEELA_PY, clean_env, strip_bundle, support_paths, work_dir

__all__ = ['ExecOutcome', 'Kernel', 'KernelStartError', 'GatewayKernel', 'GatewayService', 'KernelPool',
           'RuntimeBroker', 'KernelLimit', 'check_gateway_deps',
           'bootstrap_src', 'output_text', 'ipymini_available', 'missing_kernel_module', 'find_pythons',
           'project_python', 'nearest_python', 'python_for', 'venv_env', 'run_file_src']

KERNELS = ('ipykernel', 'ipymini')

VENV_DIRS = ('.venv', 'venv', 'env', '.env')
VENV_BINS = ('bin/python', 'Scripts/python.exe')

SHUTDOWN_WAIT = 5.0

async def _give_up_after(coro, timeout=SHUTDOWN_WAIT):
    "Await `coro`, then stop waiting rather than hold the caller open. Failing to close is not news."
    try: await asyncio.wait_for(coro, timeout=timeout)
    except Exception: pass

def ipymini_available():
    "True when the ipymini package can be imported in this interpreter."
    return importlib.util.find_spec('ipymini') is not None

def _venv_pythons(root):
    "Every conventional venv interpreter path under `root`, as `(venv dir, path)`; existence."
    root = Path(root)
    return L((d, root/d/b) for d in VENV_DIRS for b in VENV_BINS)

def project_python(roots=()):
    "The first conventional project-local virtualenv interpreter, or None."
    for root in L(roots):
        if (p := first(p for _, p in _venv_pythons(root) if p.exists())): return str(p)
    return None

def nearest_python(start, stop=None):
    "The nearest conventional venv interpreter at or above `start`, not searched past `stop`."
    try: start = Path(start).resolve()
    except Exception: return None
    stop = Path(stop).resolve() if stop else None
    for d in (start, *start.parents):
        if (p := first(p for _, p in _venv_pythons(d) if p.exists())): return str(p)
        if stop is not None and d == stop: break
    return None

def python_for(cwd=None, session=None, stop=None):
    "The interpreter anything Leela spawns for `cwd` should be inside."
    if cwd and stop is None and session is not None:
        try: stop = session.fs.root_of(cwd)
        except Exception: stop = None
    if (py := nearest_python(cwd, stop) if cwd else None): return py
    if session is None: return None
    return session.pool.default_python or project_python(session.fs.roots)

def venv_env(python, env=None):
    """`env` (this process's, by default) with `python`'s environment in front of it.

    A frozen app starts from `clean_env`. py2app points `PYTHONPATH`, `PYTHONHOME` and
    `__PYVENV_LAUNCHER__` at the bundle so its own helper starts, and a child that keeps them
    imports the bundle's standard library under another interpreter. `nbdev-test` run from the app
    died inside `linecache` doing exactly that, before it could report a single notebook.
    """
    env = strip_bundle(dict(os.environ if env is None else env))
    if not python: return env
    bindir = str(Path(python).parent)
    env['VIRTUAL_ENV'] = str(Path(bindir).parent)
    # Not `UV_PROJECT_ENVIRONMENT`. It is read wherever the process ends up, not where it started,
    # so a `uv sync` run in another checkout syncs that project's lock into this venv and prunes
    # everything the lock does not name. uv finds the right environment from the directory anyway.
    env.pop('UV_PROJECT_ENVIRONMENT', None)
    env['PATH'] = bindir + os.pathsep + env.get('PATH', '')
    env.pop('PYTHONHOME', None)
    return env

def _venv_roots(roots):
    "Each open folder and the checkouts directly inside it: one folder of repos holds a venv each."
    for r in L(roots):
        yield Path(r)
        try: yield from sorted(d for d in Path(r).iterdir() if d.is_dir() and not d.name.startswith('.'))
        except OSError: pass

def find_pythons(roots=(), current=None):
    """Interpreters a kernel could be launched under: this one, `current`, and the venvs in reach.

    `current` is what `python_for` resolved for the open tab, which the walk up can find deeper than
    a folder of checkouts is scanned. Listing it is what makes the picker able to mark it.
    """
    from shutil import which
    out, seen = L(), set()
    def add(p, label):
        p = str(p)
        if p in seen or not os.path.exists(p): return
        seen.add(p)
        out.append({'path': p, 'label': label})
    add(sys.executable, 'this one (leela’s own)')
    if current:
        d = Path(current).parents
        add(current, f'{d[2].name}/{d[1].name}' if len(d) > 2 else str(current))
    for r in _venv_roots(roots):
        for d, p in _venv_pythons(r): add(p, f'{Path(r).name}/{d}')
    for n in ('python3', 'python'):
        if (w := which(n)): add(w, f'{n} on PATH')
    return out

def run_file_src(path, src=None, argv=(), cwd=None):
    "Code that runs a file in the kernel's *own* namespace, with script semantics."
    src = open(path, encoding='utf-8').read() if src is None else src
    setup = ('import os as _lee_os, sys as _lee_sys\n'
        f'_lee_code = compile({src!r}, {str(path)!r}, "exec")\n'
        '_lee_argv, _lee_cwd = _lee_sys.argv, _lee_os.getcwd()\n'
        f'_lee_sys.argv = [{str(path)!r}, *{list(argv)!r}]\n')
    if cwd: setup += f'_lee_os.chdir({str(cwd)!r})\n'
    return setup + ('try: exec(_lee_code)\n'
        'finally:\n'
        '    _lee_sys.argv = _lee_argv\n'
        '    _lee_os.chdir(_lee_cwd)\n'
        '    del _lee_os, _lee_sys, _lee_code, _lee_argv, _lee_cwd\n')

BOOTSTRAP = '''
def _lee_bootstrap():
	import sys, importlib.util
	# Borrowed only by a kernel of Leela's own minor version. A frozen build ships bytecode-only
	# modules in its zip, and another version reads their magic number and refuses: an import that
	# fell through to them died as `bad magic number`, not as anything about the inspector.
	if tuple(sys.version_info[:2]) == tuple({version!r}):
		for _p in {support!r}:
			if _p and _p not in sys.path: sys.path.append(_p)
	# The project venv may contain an older dhrishti. Pin the inspector protocol to this
	# Leela installation while every other import stays project-local. Best-effort: a frozen
	# build imports dhrishti out of a zip, where there is no file to point at. A failed pin
	# must leave nothing in sys.modules, or the fallback import finds the broken module.
	try:
		if tuple(sys.version_info[:2]) != tuple({version!r}): raise ImportError('another Python')
		for _n in [n for n in sys.modules if n == 'dhrishti' or n.startswith('dhrishti.')]:
			del sys.modules[_n]
		_spec = importlib.util.spec_from_file_location('dhrishti', {dhrishti_init!r},
			submodule_search_locations=[{dhrishti_dir!r}])
		_pkg = importlib.util.module_from_spec(_spec)
		sys.modules['dhrishti'] = _pkg
		_spec.loader.exec_module(_pkg)
	except Exception:
		for _n in [n for n in sys.modules if n == 'dhrishti' or n.startswith('dhrishti.')]:
			del sys.modules[_n]
	import dhrishti.serving as ls
	r = ls.serve_in_kernel(name={name!r}, port={port!r}, agent={agent!r}, token={token!r},
	                       session_dir='_leela_sessions', agent_session_dir='_leela_agent_sessions')
	if {ipymini!r}:
		try:
			from IPython import get_ipython
			ls.set_kernel_backend(getattr(get_ipython(), 'kernel', None))
		except Exception: ls.set_kernel_backend(None)
	return r
try: _lee_bootstrap()
finally: del _lee_bootstrap
'''

def bootstrap_src(name=None, port=8000, agent='restricted', token=True, kernel='ipykernel'):
    "The bootstrap cell source for a kernel that should host an inspector."
    support = support_paths()
    # Found, not imported: importing dhrishti for its `__file__` drags IPython, pandas and
    # numpy into the Leela server, which has no use for them. The kernel does the importing.
    spec = importlib.util.find_spec('dhrishti')
    if spec is None or not spec.origin: raise RuntimeError('dhrishti is not installed')
    dhrishti_init = str(Path(spec.origin).resolve())
    return BOOTSTRAP.format(name=name, port=port, agent=agent, token=token, support=support,
        version=LEELA_PY, dhrishti_init=dhrishti_init,
        dhrishti_dir=str(Path(dhrishti_init).parent), ipymini=(kernel == 'ipymini'))

def output_text(outs):
    "Flatten nbformat outputs to plain text: the terminal rendering, and the agent's view of a run."
    parts = L()
    for o in outs:
        t = o.get('output_type')
        if t == 'stream': parts.append(o.get('text', ''))
        elif t == 'error': parts.append('\n'.join(o.get('traceback') or [f"{o.get('ename')}: {o.get('evalue')}"]))
        elif t in ('execute_result', 'display_data'):
            d = o.get('data') or {}
            parts.append(d.get('text/markdown') or d.get('text/plain') or next((f'[{k}]' for k in d), ''))
    return ''.join(parts)

@dataclass
class ExecOutcome:
    "Result of one execute_request: nbformat-shaped outputs plus the shell reply status."
    ok: bool = True
    execution_count: int | None = None
    outputs: list = field(default_factory=list)
    error: str | None = None
    @property
    def text(self): return output_text(self.outputs)

def _runtime_python(python=None):
    "A selected interpreter, or py2app's bundled generic Python helper."
    if python: return str(python)
    if getattr(sys, 'frozen', False):
        helper = Path(sys.executable).with_name('python')
        if helper.exists(): return str(helper)
    return sys.executable

class KernelStartError(RuntimeError):
    "A kernel that could not start, said in terms of the environment rather than the protocol."

def missing_kernel_module(python=None, kernel='ipykernel'):
    """The kernel package `python` cannot import, or None.

    A venv without it exits before the first message, and jupyter_client can only report that the
    kernel died before replying to `kernel_info`. Asked here, the environment says which module it
    is short of. Only the failure path pays for this.
    """
    mod = 'ipymini' if kernel == 'ipymini' else 'ipykernel_launcher'
    exe = _runtime_python(python)
    if exe == sys.executable: return None if importlib.util.find_spec(mod) else mod
    src = f"import importlib.util, sys; sys.exit(0 if importlib.util.find_spec({mod!r}) else 1)"
    try: r = subprocess.run([exe, '-c', src], capture_output=True, timeout=20, env=clean_env())
    except (OSError, subprocess.SubprocessError): return None   # cannot tell, so do not say
    return None if r.returncode == 0 else mod

def _frozen_pythonpath():
    "Module and extension paths a py2app helper process must inherit."
    if not getattr(sys, 'frozen', False): return None
    resources = Path(sys.executable).resolve().parent.parent/'Resources'
    version = f'python{sys.version_info.major}.{sys.version_info.minor}'
    bundled = [resources/'lib'/version, resources/'lib'/version/'lib-dynload',
        resources/'lib'/f'python{sys.version_info.major}{sys.version_info.minor}.zip']
    return os.pathsep.join(dict.fromkeys(str(p) for p in [*bundled, *sys.path] if p))

def _kernel_env(python=None):
    "Environment for a kernel child, detached from py2app's interpreter redirect."
    env = clean_env()
    if python is None and (path := _frozen_pythonpath()): env['PYTHONPATH'] = path
    return env

def _spec(python=None, name='python3', kernel='ipykernel'):
    "A kernelspec pinned to a specific interpreter, so the kernel runs in *this* venv."
    runtime = _runtime_python(python)
    if kernel == 'ipymini': argv = [runtime, '-Xfrozen_modules=off', '-m', 'ipymini', '-f', '{connection_file}']
    else: argv = [runtime, '-m', 'ipykernel_launcher', '-f', '{connection_file}']
    metadata = {'supported_encryption': 'curve'} if kernel == 'ipykernel' else {}
    return KernelSpec(argv=argv, display_name=name, language='python', metadata=metadata)

class _Inspector:
    "The inspector-client half shared by `Kernel` and `GatewayKernel`."
    last_used = 0.
    def touch(self):
        "Stamp activity. The idle sweep measures from here, so anything that uses a kernel says so."
        self.last_used = time.time()
        return self
    @property
    def busy(self):
        "A cell is running on this kernel. The sweep never takes one of these."
        t = getattr(self, '_exec_task', None)
        return t is not None and not t.done()
    @property
    def idle_for(self):
        "Seconds since this kernel was last used; 0 while it is running something."
        return 0. if self.busy else max(0., time.time() - self.last_used)
    @property
    def kernel_kind(self):
        "Which launcher this kernel was started with: 'ipykernel' or 'ipymini'."
        return self.kernel
    @property
    def token(self):
        "Owner token for this kernel's inspector, so the IDE may use its gated endpoints."
        if not self.base: return None
        try: return (reg_dir()/f"token-{self.base.rsplit(':', 1)[-1]}").read_text().strip() or None
        except Exception: return None
    def _headers(self): return {'X-Dhrishti-Token': t} if (t := self.token) else {}
    @property
    def _boot_name(self):
        "The name the in-kernel inspector registers itself under."
        return self.name
    async def bootstrap(self):
        "Start the inspector inside the kernel and record its base URL."
        src = bootstrap_src(self._boot_name, self.port, self.agent, True, self.kernel)
        r = await self.execute(src, silent=True, store_history=False)
        if not r.ok:
            self.boot_error = r.error or r.text or 'inspector bootstrap failed'
            return None
        self.base = await self._find_base()
        if self.base is None: self.boot_error = 'inspector started but did not register'
        return self.base
    async def api(self, path, params=None, timeout=15):
        "GET this kernel's own inspector, carrying its owner token; None if it has none."
        if not self.base: return None
        import httpx2 as httpx
        try:
            async with httpx.AsyncClient(base_url=self.base, timeout=timeout, headers=self._headers()) as c:
                r = await c.get(path, params=params or {})
                r.raise_for_status()
                self.last_api_error = ''
                return r.json()
        except Exception as e:
            self.last_api_error = f'{type(e).__name__}: {e}'
            return None
    def api_sync(self, path, params=None, timeout=30):
        "Synchronous inspector call for model tools running on an agent worker thread."
        if not self.base: return None
        import httpx2 as httpx
        try:
            with httpx.Client(base_url=self.base, timeout=timeout, headers=self._headers()) as c:
                r = c.get(path, params=params or {})
                r.raise_for_status()
                self.last_api_error = ''
                return r.json()
        except Exception as e:
            self.last_api_error = f'{type(e).__name__}: {e}'
            return None
    async def names(self, scope='live', profile='full'):
        "Every top-level name in this kernel's namespace, or the agent sandbox's."
        base = '/agent/api/rows' if scope == 'isolated' else '/api/rows'
        r = await self.api(base, {'profile': profile, 'sort': 'name'})
        return L(n.get('name', '') for g in (r or {}).get('groups', []) for n in g.get('nodes', []))
    async def stop(self, timeout=2.0):
        "Interrupt the active execution, then restart the kernel if it ignores the deadline."
        task = self._exec_task
        if task is None or task.done(): return {'ok': False, 'forced': False, 'note': 'nothing is running'}
        await self.interrupt()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
            return {'ok': True, 'forced': False, 'note': 'cell interrupted'}
        except asyncio.TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await self.restart()
            return {'ok': True, 'forced': True, 'note': 'kernel restarted after interrupt was ignored'}
        except asyncio.CancelledError: return {'ok': True, 'forced': False, 'note': 'cell stopped'}

class Kernel(_Inspector):
    "One ipykernel process: execute/complete over jupyter_client, live variables over its in-kernel."
    def __init__(self,
        cwd=None,
        name=None,
        python=None,
        inspect=True,
        agent='restricted',
        port=8000,
        kernel='ipykernel',
    ):
        if kernel not in KERNELS: kernel = 'ipykernel'
        if kernel == 'ipymini' and not ipymini_available():
            warnings.warn("ipymini is unavailable in this interpreter; falling back to ipykernel. "
                "Install project kernel support from Leela's kernel picker.")
            kernel = 'ipykernel'
        store_attr()
        self.km = self.kc = None
        self._ipc_dir = None
        self.base = None
        self.boot_error = None
        self.last_api_error = ''
        self._exec_lock = asyncio.Lock()
        self._exec_task = None
        self._shell_lock = asyncio.Lock()
        self._debug_lock = asyncio.Lock()
        self._debug_seq = 0
        self._debug_thread = None
        self._debug_source = None
        self._debug_sources = {}
    @property
    def alive(self):
        "True only once the process and its usable client are both ready."
        return self.km is not None and self.kc is not None and self.km.has_kernel
    @property
    def pid(self):
        "OS pid of the kernel process, or None."
        p = getattr(getattr(self.km, 'provisioner', None), 'process', None)
        return getattr(p, 'pid', None)
    async def start(self, timeout=60):
        "Launch the kernel, wait for it to answer, then bootstrap its inspector."
        manager_kw = {'kernel_name': self.kernel if self.kernel == 'ipymini' else 'python3'}
        if os.name != 'nt' and self.kernel == 'ipykernel':
            self._ipc_dir = tempfile.mkdtemp(prefix='lee-k-', dir='/tmp' if os.path.isdir('/tmp') else None)
            manager_kw.update(transport='ipc', ip=os.path.join(self._ipc_dir, 'k'))
        elif os.name != 'nt': manager_kw.update(transport='tcp', ip='127.0.0.1')
        elif self.kernel == 'ipykernel':
            manager_kw['transport_encryption'] = 'required'
        self.km = AsyncKernelManager(**manager_kw)
        self.km._kernel_spec = _spec(self.python, ifnone(self.name, 'python3'), self.kernel)
        cwd = work_dir(self.cwd)
        try:
            await self.km.start_kernel(cwd=cwd, env=_kernel_env(self.python))
            client_kw = {}
            if getattr(self.km, 'curve_publickey', None) is not None:
                client_kw.update(curve_publickey=self.km.curve_publickey,
                    curve_secretkey=self.km.curve_secretkey)
            self.kc = self.km.client(**client_kw)
            self.kc.start_channels()
            await self.kc.wait_for_ready(timeout=timeout)
        except BaseException as e:
            await self.shutdown()
            if isinstance(e, Exception) and (mod := missing_kernel_module(self.python, self.kernel)):
                raise KernelStartError(
                    f'{_runtime_python(self.python)} cannot import {mod}, so it can run no kernel. '
                    f'Run `uv sync` in that project, or pick another interpreter in the kernel picker.') from e
            raise
        if self.inspect: await self.bootstrap()
        return self
    async def _find_base(self):
        "The registry entry written by our own kernel process, matched on pid."
        for _ in range(40):
            if (e := first(active(), lambda e: e.get('pid') == self.pid)): return e['base']
            await asyncio.sleep(0.05)
        return None
    async def interrupt(self):
        "Request cooperative cancellation; callers needing a guarantee should use stop()."
        if self.km: await self.km.interrupt_kernel()
    async def restart(self):
        "Restart the process; the namespace and the in-kernel inspector are both rebuilt."
        if not self.km: return
        self.base = self.boot_error = None
        await self.km.restart_kernel(now=False)
        await self.kc.wait_for_ready(timeout=60)
        if self.inspect: await self.bootstrap()
    async def shutdown(self):
        if self.kc:
            try: self.kc.stop_channels()
            except Exception: pass
        if self.km and self.km.has_kernel:
            try: await self.km.shutdown_kernel(now=False)
            except Exception: pass
        self.km = self.kc = self.base = None
        if self._ipc_dir:
            shutil.rmtree(self._ipc_dir, ignore_errors=True)
            self._ipc_dir = None
    async def execute(self, code, silent=False, store_history=True, on_output=None, timeout=None,
        on_debug=None):
        "Run `code` on the shell channel and collect nbformat-shaped outputs, streaming each to `on_output`."
        if not self.alive: return ExecOutcome(ok=False, error='kernel is not running')
        async with self._exec_lock, self._shell_lock:
            if not self.alive: return ExecOutcome(ok=False, error='kernel is not running')
            task = asyncio.current_task()
            self._exec_task = task
            self.touch()
            try:
                msg_id = self.kc.execute(code, silent=silent, store_history=store_history,
                    allow_stdin=False)
                outs = await self._collect(msg_id, on_output, timeout, on_debug)
                reply = await self._reply(msg_id, timeout)
            finally:
                self.touch()
                if self._exec_task is task: self._exec_task = None
        c = reply.get('content', {}) if reply else {}
        err = None
        if c.get('status') == 'error': err = f"{c.get('ename')}: {c.get('evalue')}"
        elif c.get('status') == 'abort': err = 'aborted'
        if err is None and (e := first(outs, lambda o: o['output_type'] == 'error')): err = f"{e.get('ename')}: {e.get('evalue')}"
        return ExecOutcome(ok=err is None, execution_count=c.get('execution_count'), outputs=outs, error=err)
    async def _collect(self, msg_id, on_output=None, timeout=None, on_debug=None):
        "Drain iopub for one request, applying Jupyter display-id updates in place."
        outs, displays = [], {}
        while True:
            try: msg = await self.kc.get_iopub_msg(timeout=timeout or 0.5)
            except (queue.Empty, asyncio.TimeoutError):
                if not self.alive: break
                continue
            t, c = msg['header']['msg_type'], msg['content']
            if t == 'debug_event':
                if c.get('event') == 'stopped': self._debug_thread = (c.get('body') or {}).get('threadId')
                elif c.get('event') == 'continued': self._debug_thread = None
                if on_debug: on_debug(c)
                continue
            if (msg.get('parent_header') or {}).get('msg_id') != msg_id: continue
            if t == 'status':
                if c.get('execution_state') == 'idle': break
            elif t == 'clear_output': outs.clear()
            elif o := self._as_output(t, c):
                display_id = (c.get('transient') or {}).get('display_id')
                if t == 'update_display_data' and display_id in displays:
                    outs[displays[display_id]] = o
                elif (o['output_type'] == 'stream' and outs and outs[-1].get('output_type') == 'stream'
                    and outs[-1].get('name') == o['name']): outs[-1]['text'] += o['text']
                else:
                    outs.append(o)
                    if display_id: displays[display_id] = len(outs) - 1
                if on_output:
                    event = dict(o)
                    if display_id: event.update(_display_id=display_id, _update=(t == 'update_display_data'))
                    on_output(event)
        return outs
    @staticmethod
    def _as_output(msg_type, c):
        "An iopub message as an nbformat output dict, or None if it carries no output."
        if msg_type == 'stream': return {'output_type': 'stream', 'name': c.get('name', 'stdout'), 'text': c.get('text', '')}
        if msg_type == 'error':
            return {'output_type': 'error', 'ename': c.get('ename', ''), 'evalue': c.get('evalue', ''),
                'traceback': list(c.get('traceback') or [])}
        if msg_type in ('execute_result', 'display_data', 'update_display_data'):
            o = {'output_type': 'execute_result' if msg_type == 'execute_result' else 'display_data',
                'data': c.get('data') or {}, 'metadata': c.get('metadata') or {}}
            if msg_type == 'execute_result': o['execution_count'] = c.get('execution_count')
            return o
        return None
    async def _reply(self, msg_id, timeout=None):
        "The shell reply for one request, skipping replies to anything else."
        while True:
            try: msg = await self.kc.get_shell_msg(timeout=timeout or 10)
            except (queue.Empty, asyncio.TimeoutError): return None
            if (msg.get('parent_header') or {}).get('msg_id') == msg_id: return msg
    async def debug_request(self, command, arguments=None, timeout=15):
        "Send one Jupyter Debug Protocol/DAP request over ipykernel's control channel."
        if self.kernel != 'ipykernel': raise RuntimeError('cell debugging currently requires an ipykernel runtime')
        if not self.alive: raise RuntimeError('kernel is not running')
        async with self._debug_lock:
            self._debug_seq += 1
            content = {'seq': self._debug_seq, 'type': 'request', 'command': command,
                'arguments': arguments or {}}
            msg = self.kc.session.msg('debug_request', content=content)
            self.kc.control_channel.send(msg)
            while True:
                try: reply = await self.kc.get_control_msg(timeout=timeout)
                except (queue.Empty, asyncio.TimeoutError):
                    raise TimeoutError(f'debugger did not answer {command}')
                if (reply.get('parent_header') or {}).get('msg_id') != msg['header']['msg_id']: continue
                out = reply.get('content') or {}
                if not out.get('success', False): raise RuntimeError(out.get('message') or f'debugger rejected {command}')
                return out
    async def debug_start(self, code, breakpoints=(), notebook_cells=()):
        "Initialize debugpy and map every notebook cell source to ipykernel's debug files."
        await self.debug_request('initialize', {
            'clientID': 'leela', 'clientName': 'Leela', 'adapterID': 'python',
            'pathFormat': 'path', 'linesStartAt1': True, 'columnsStartAt1': True,
            'supportsVariableType': True, 'supportsVariablePaging': True,
        })
        await self.debug_request('attach')
        self._debug_sources = {}
        for cell_id, source in notebook_cells:
            dumped = await self.debug_request('dumpCell', {'code': source})
            if (path := dumped.get('body', {}).get('sourcePath')): self._debug_sources[path] = cell_id
        dumped = await self.debug_request('dumpCell', {'code': code})
        self._debug_source = dumped.get('body', {}).get('sourcePath')
        if not self._debug_source: raise RuntimeError('ipykernel did not create a debug source for the cell')
        requested = [{'line': max(1, int(line))} for line in breakpoints]
        set_reply = await self.debug_request('setBreakpoints', {
            'source': {'path': self._debug_source}, 'breakpoints': requested,
            'sourceModified': False,
        })
        await self.debug_request('configurationDone')
        return [b.get('line') for b in set_reply.get('body', {}).get('breakpoints', [])
            if b.get('verified', True)]
    async def debug_variables(self, reference, start=0, count=200):
        "Children of one paused DAP variable, preserving references for recursive expansion."
        reply = await self.debug_request('variables', {
            'variablesReference': int(reference), 'start': int(start), 'count': int(count),
        })
        return reply.get('body', {}).get('variables', [])
    async def debug_state(self, thread_id=None, frame_id=None):
        "The paused call stack and locals for the selected frame, normalized for the browser."
        thread_id = int(thread_id or self._debug_thread or 0)
        if not thread_id: return {'paused': False, 'frames': [], 'variables': []}
        stack = await self.debug_request('stackTrace', {'threadId': thread_id,
            'startFrame': 0, 'levels': 50})
        frames = stack.get('body', {}).get('stackFrames', [])
        selected = first(frames, lambda f: f.get('id') == int(frame_id or -1)) or first(frames)
        variables, scopes = [], []
        if selected:
            scope_reply = await self.debug_request('scopes', {'frameId': selected['id']})
            scopes = scope_reply.get('body', {}).get('scopes', [])
            local = first(scopes, lambda s: s.get('name', '').lower() == 'locals') or first(scopes)
            if local and local.get('variablesReference'): variables = await self.debug_variables(local['variablesReference'])
        return {'paused': True, 'thread_id': thread_id, 'frame_id': selected.get('id') if selected else None,
            'frames': frames, 'scopes': scopes, 'variables': variables,
            'source': self._debug_source}
    async def debug_evaluate(self, expression, frame_id=None):
        "Evaluate an expression in the selected paused frame, the debugger's exec console."
        if not self._debug_thread: raise RuntimeError('the debugger is not paused')
        if frame_id is None:
            state = await self.debug_state()
            frame_id = state.get('frame_id')
        reply = await self.debug_request('evaluate', {
            'expression': str(expression), 'frameId': int(frame_id), 'context': 'repl',
        })
        return reply.get('body', {})
    async def debug_complete(self, code, pos, frame_id=None):
        "Completions from the paused frame without queueing a shell request behind it."
        if frame_id is None:
            state = await self.debug_state()
            frame_id = state.get('frame_id')
        reply = await self.debug_request('completions', {
            'text': str(code), 'column': int(pos) + 1, 'frameId': int(frame_id),
        })
        targets = reply.get('body', {}).get('targets', [])
        return {'from': int(pos), 'matches': [t.get('text') or t.get('label') for t in targets
            if t.get('text') or t.get('label')][:50]}
    async def debug_control(self, command, thread_id=None):
        if command not in {'continue', 'next', 'stepIn', 'stepOut', 'pause'}: raise ValueError(f'unknown debug command {command!r}')
        tid = int(thread_id or self._debug_thread or 0)
        if not tid: raise RuntimeError('the debugger is not paused')
        out = await self.debug_request(command, {'threadId': tid})
        if command != 'pause': self._debug_thread = None
        return out
    async def debug_stop(self):
        if self.kernel != 'ipykernel': return
        try: await self.debug_request('disconnect', {'restart': False, 'terminateDebuggee': False})
        finally:
            self._debug_thread = self._debug_source = None
            self._debug_sources = {}
    async def complete(self, code, pos):
        "Completions at `pos` in the browser's `{from, matches}` response shape."
        if not self.alive: return {'from': pos, 'matches': []}
        async with self._shell_lock:
            msg_id = self.kc.complete(code, pos)
            r = await self._reply(msg_id)
        c = (r or {}).get('content', {})
        return {'from': c.get('cursor_start', pos), 'matches': list(c.get('matches') or [])[:50]}
    async def inspect_obj(self, code, pos, detail=0):
        "Kernel-side introspection (signature and docstring) for the object at `pos`; '' when unknown."
        if not self.alive: return ''
        async with self._shell_lock:
            msg_id = self.kc.inspect(code, pos, detail_level=detail)
            r = await self._reply(msg_id)
        c = (r or {}).get('content', {})
        if not c.get('found'): return ''
        return strip_ansi((c.get('data') or {}).get('text/plain') or '')

#: What the `[gateway]` extra installs, with the version range each import has to satisfy.
#: `jupyasyncclient` 0.2.8 leaves the gateway executing nothing, so it is excluded here as in `pyproject.toml`.
GATEWAY_DEPS = (('jupygate', ''), ('jupyasyncclient', '>=0.2.1,!=0.2.8'))

def check_gateway_deps():
    "Raise a RuntimeError naming the distribution when the `[gateway]` extra is missing or out of range."
    import importlib.metadata
    from packaging.specifiers import SpecifierSet
    for name, spec in GATEWAY_DEPS:
        try: importlib.import_module(name)
        except ImportError as e: raise RuntimeError(
            f'gateway transport needs `pip install "leela[gateway]"`; {name} is not installed') from e
        if not spec: continue
        try: version = importlib.metadata.version(name)
        except Exception: continue   # unknown version, such as a vendored copy, is not a reason to refuse
        if not SpecifierSet(spec, prereleases=True).contains(version): raise RuntimeError(
            f'gateway transport needs {name}{spec}, and {version} is installed; '
            'reinstall with `pip install "leela[gateway]"`')

class GatewayService:
    "One supervised jupygate for all workspace kernels in this Leela process."
    def __init__(self, port=8787, token=None):
        import secrets
        self.port, self.token, self.server = int(port), token or secrets.token_urlsafe(24), None
    @property
    def url(self): return getattr(self.server, 'url', None) or f'http://127.0.0.1:{self.port}'
    def start(self):
        check_gateway_deps()   # both imports, before the early return, so every kernel start is covered
        if self.server is not None: return self
        from jupygate.core import create_app, serve
        argv = [sys.executable, '-m', 'ipykernel_launcher', '-f', '{connection_file}']
        try: self.server = serve(create_app(argv=argv, auth_token=self.token), port=self.port, in_thread=True)
        except OSError as e: raise RuntimeError(   # jupygate gives up on the listen with a TimeoutError
            f'gateway transport could not listen on port {self.port}; another Leela or a leftover '
            'gateway is holding it') from e
        return self
    def stop(self):
        if self.server is not None: self.server.should_exit = True

class GatewayKernel(_Inspector):
    "The `Kernel` interface over jupygate + jupyasyncclient, so a kernel outlives a client reconnect."
    def __init__(self, gateway, cwd=None, name=None, python=None, inspect=True,
        agent='restricted', port=8000, kernel='ipykernel'):
        store_attr()
        if self.kernel not in KERNELS: self.kernel = 'ipykernel'
        if self.kernel == 'ipymini' and not ipymini_available():
            warnings.warn('ipymini not installed; falling back to ipykernel')
            self.kernel = 'ipykernel'
        self.kc, self.base, self.boot_error, self._alive = None, None, None, False
        self.last_api_error = ''
        self._registry_name = f'{self.name or "kernel"}:{uuid.uuid4().hex[:10]}'
        self._exec_lock = asyncio.Lock()
        self._exec_task = None
    @property
    def alive(self): return self._alive and self.kc is not None
    @property
    def pid(self): return None
    async def start(self, timeout=60):
        check_gateway_deps()
        from jupyasyncclient import JupyAsyncKernelClient
        self.gateway.start()
        argv = _spec(self.python, ifnone(self.name, 'python3'), self.kernel).argv
        self.kc = await JupyAsyncKernelClient.connect(self.gateway.url, token=self.gateway.token,
            timeout=timeout, argv=argv,
            env=_kernel_env(self.python),
            cwd=work_dir(self.cwd))
        self._alive = True
        if self.inspect: await self.bootstrap()
        return self
    @property
    def _boot_name(self):
        "jupygate exposes no pid, so the registry entry is matched on a name unique to this kernel."
        return self._registry_name
    async def _find_base(self):
        "The registry entry written by this kernel, matched on its unique name."
        for _ in range(60):
            if rows := [e for e in active() if e.get('name') == self._registry_name]: return rows[-1]['base']
            await asyncio.sleep(.05)
        return None
    async def execute(self, code, silent=False, store_history=True, on_output=None, timeout=None):
        if not self.alive: return ExecOutcome(ok=False, error='kernel is not running')
        async with self._exec_lock:
            task = asyncio.current_task()
            self._exec_task = task
            self.touch()
            run = self.kc.run(code, silent=silent, store_history=store_history)
            outputs = []
            try:
                async for output in run:
                    outputs.append(output)
                    if on_output: on_output(output)
            except Exception as e: return ExecOutcome(ok=False, outputs=outputs, error=str(e))
            finally:
                self.touch()
                if self._exec_task is task: self._exec_task = None
        reply = (run.reply or {}).get('content', {})
        error = None if run.status == 'ok' else f"{reply.get('ename', run.status)}: {reply.get('evalue', '')}".rstrip(': ')
        return ExecOutcome(ok=error is None, execution_count=run.execution_count,
            outputs=outputs, error=error)
    async def complete(self, code, pos):
        if not self.alive: return {'from': pos, 'matches': []}
        matches, start = await self.kc.complete(code, pos)
        return {'from': start, 'matches': list(matches)[:50]}
    async def inspect_obj(self, code, pos, detail=0):
        if not self.alive: return ''
        return strip_ansi(await self.kc.inspect(code, pos, detail_level=detail))
    async def interrupt(self):
        "Request cooperative cancellation through jupygate's kernel control endpoint."
        if self.kc: await self.kc.interrupt_kernel()
    async def restart(self):
        if not self.kc: return
        self.base = self.boot_error = None
        await self.kc.restart_kernel(); await self.kc.wait_for_ready(timeout=60)
        if self.inspect: await self.bootstrap()
    async def _release(self):
        await self.kc.shutdown_kernel()
        await self.kc.aclose()
    async def shutdown(self):
        if self.kc: await _give_up_after(self._release())
        self.kc, self.base, self._alive = None, None, False

#: How long a kernel may sit unused before the sweep closes it. `LEELA_KERNEL_IDLE=0` turns it off.
IDLE_SECONDS = 30*60
#: How often the sweep looks.
SWEEP_SECONDS = 60

class KernelLimit(RuntimeError):
    "The ceiling is reached. `candidate` is a kernel that can be offered to close, or None while all are busy."
    def __init__(self, msg, candidate=None, limit=0):
        super().__init__(msg)
        self.candidate, self.limit = candidate, limit

class RuntimeBroker:
    "Process ceiling across the kernel pools of every web workspace. Never evicts a live namespace."
    def __init__(self, max_kernels=None, auto_manage=None):
        self.max_kernels = int(max_kernels or os.environ.get('LEELA_MAX_KERNELS', 12))
        self.auto_manage = bool(ifnone(auto_manage,
            os.environ.get('LEELA_KERNEL_AUTO', '').lower() in ('1', 'true', 'yes')))
        self.pools, self._lock, self._reserved = [], asyncio.Lock(), set()
    def register(self, pool):
        if pool not in self.pools: self.pools.append(pool)
        pool.broker = self
        return pool
    @property
    def live(self):
        return [(pool, key, kernel) for pool in self.pools for key, kernel in pool.kernels.items()
            if kernel.alive]
    def status(self):
        return {'live': len(self.live), 'limit': self.max_kernels,
            'runtimes': [{'key': str(key), 'pid': kernel.pid, 'kind': kernel.kernel_kind,
                'cwd': str(kernel.cwd or '')} for _, key, kernel in self.live]}
    def stalest(self):
        "The idle kernel that has waited longest, as `(pool, key, kernel)`. None while all are busy."
        idle = [row for row in self.live if not row[2].busy]
        return max(idle, key=lambda row: row[2].idle_for) if idle else None
    def _candidate(self):
        "What the limit dialog needs to name the kernel it is offering to close."
        if (row := self.stalest()) is None: return None
        _, key, k = row
        return {'key': str(key), 'name': Path(str(getattr(k, 'cwd', '') or key)).name,
                'cwd': str(getattr(k, 'cwd', '') or ''), 'pid': getattr(k, 'pid', None),
                'idle_for': int(k.idle_for)}
    async def admit(self, pool, key):
        token, evicted = (id(pool), key), None
        async with self._lock:
            if token in self._reserved or key in pool._starting: return
            if len(self.live) + len(self._reserved) >= self.max_kernels:
                row = self.stalest()
                if row is None: raise KernelLimit(
                    f'kernel limit reached ({self.max_kernels}) and every runtime is busy; stop one '
                    'or set LEELA_MAX_KERNELS to a larger value', limit=self.max_kernels)
                if not self.auto_manage: raise KernelLimit(
                    f'kernel limit reached ({self.max_kernels}); close an idle runtime '
                    'or set LEELA_MAX_KERNELS to a larger value',
                    candidate=self._candidate(), limit=self.max_kernels)
                evicted = self._candidate()
                vpool, vkey, _ = row
                await vpool.close(vkey)   # `close` never takes this lock, so holding it is safe
            self._reserved.add(token)
        return evicted
    async def release(self, pool, key):
        async with self._lock: self._reserved.discard((id(pool), key))

class KernelPool:
    "The IDE's kernels, keyed by an id the workspace assigns (usually a tab or a folder root)."
    def __init__(self, port=8000, default_kernel='ipykernel', default_python=None, broker=None,
        transport='direct', gateway=None, idle=None):
        self.port, self.kernels, self._starting, self.broker = port, {}, {}, None
        self.idle = int(ifnone(idle, os.environ.get('LEELA_KERNEL_IDLE', IDLE_SECONDS)))
        self._sweep = None
        self.transport = transport if transport in ('direct', 'gateway') else 'direct'
        self.gateway = gateway
        if broker is not None: broker.register(self)
        self.default_kernel = default_kernel if default_kernel in KERNELS else 'ipykernel'
        self.default_python = default_python
    def choose(self,
        kernel=None,
        python=False,
    ):
        "Set what the *next* kernel starts as. Running kernels are left alone."
        if kernel and kernel in KERNELS: self.default_kernel = kernel
        if python is not False: self.default_python = python
        return {'kernel': self.default_kernel, 'python': self.default_python}
    async def get(self, key, **kw):
        "The kernel for `key`, starting it once even when several browser panels ask together."
        self._sweeping()
        if (task := self._starting.get(key)) is not None: return await asyncio.shield(task)
        if (k := self.kernels.get(key)) is not None and k.alive: return k.touch()
        evicted = await self.broker.admit(self, key) if self.broker is not None else None
        async def start_one():
            kw.setdefault('kernel', self.default_kernel)
            kw.setdefault('python', self.default_python)
            cls = GatewayKernel if self.transport == 'gateway' else Kernel
            if cls is GatewayKernel:
                if self.gateway is None: self.gateway = GatewayService().start()
                kw['gateway'] = self.gateway
            k = self.kernels[key] = cls(port=self.port, **kw)
            k.evicted = evicted
            k.touch()
            try: return await k.start()
            except BaseException:
                if self.kernels.get(key) is k: self.kernels.pop(key, None)
                raise
        task = self._starting.get(key)
        if task is None: task = self._starting[key] = asyncio.create_task(start_one())
        try:
            return await asyncio.shield(task)
        finally:
            if task.done() and self._starting.get(key) is task:
                self._starting.pop(key, None)
                if self.broker is not None: await self.broker.release(self, key)
    async def reap(self):
        "Close what nobody has touched for `idle` seconds. A running cell is never taken."
        if self.idle <= 0: return []
        stale = [k for k, v in self.kernels.items()
                 if k not in self._starting and not v.busy and v.idle_for > self.idle]
        for k in stale: await self.close(k)
        return stale
    def _sweeping(self):
        "Start the idle sweep on first use: `get` is the only thing that ever adds a kernel."
        if self.idle > 0 and (self._sweep is None or self._sweep.done()):
            self._sweep = asyncio.create_task(self._sweep_loop())
    async def _sweep_loop(self):
        while True:
            await asyncio.sleep(min(SWEEP_SECONDS, max(1, self.idle)))
            try: await self.reap()
            except asyncio.CancelledError: raise
            except Exception: pass
    def peek(self, key):
        "A completed live kernel, never the object currently being started."
        if key in self._starting: return None
        k = self.kernels.get(key)
        return k if k is not None and k.alive else None
    async def close(self, key):
        if (task := self._starting.get(key)) is not None:
            try: await asyncio.shield(task)
            except BaseException: pass
        if (k := self.kernels.pop(key, None)) is not None: await k.shutdown()
    async def close_all(self):
        if self._sweep is not None: self._sweep.cancel(); self._sweep = None
        tasks = list(self._starting.values())
        if tasks: await asyncio.gather(*[asyncio.shield(task) for task in tasks], return_exceptions=True)
        await asyncio.gather(*[k.shutdown() for k in self.kernels.values()], return_exceptions=True)
        self.kernels.clear()
