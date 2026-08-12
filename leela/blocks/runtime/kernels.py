"""Managed ipykernels, each hosting its own leela inspector.

This is the pivot away from `get_ipython()`. A notebook tab owns a `Kernel`: a
real ipykernel process driven over `jupyter_client`, which the IDE talks to on
*two* channels, deliberately split:

- **execution** goes down the kernel's shell channel, so exec-strip code and
  notebook cells share one serialised queue, stream their output back over
  iopub, and are interruptible like any cell.
- **inspection** goes over HTTP to a `dhrishti` server started *inside* that
  kernel by `bootstrap()`. Shell messages queue behind a running cell, so a
  comm-based variable tree would freeze during exactly the long cell you most
  want to watch; a background thread in the kernel does not.

The in-kernel server registers itself in leela's registry, so a kernel started
here shows up as just another env to the web panel and to the env picker -- no
new discovery mechanism.

The launcher is pluggable: `kernel='ipykernel'` (the default) uses ipykernel and
matches historical behaviour exactly. `kernel='ipymini'` launches the pure-Python
[ipymini](https://github.com/AnswerDotAI/ipymini) kernel instead. ipymini adds
`get_ipython().kernel.subshell()` / `.unlock()` helpers so leela's in-kernel HTTP
handlers (`/agent/api/exec`, `/api/exec`) can execute *alongside* a running cell
rather than sharing its GIL slice. The two-channel split above is preserved --
ipymini is a drop-in kernel launcher, not a new inspection transport."""

from __future__ import annotations
import asyncio, importlib.util, os, sys, queue, shutil, tempfile, warnings
from dataclasses import dataclass, field
from pathlib import Path
from fastcore.all import store_attr, ifnone, L
from fastcore.ansi import strip_ansi
from jupyter_client.manager import AsyncKernelManager
from jupyter_client.kernelspec import KernelSpec

from dhrishti.serving import reg_dir, active

__all__ = ['ExecOutcome', 'Kernel', 'GatewayKernel', 'GatewayService', 'KernelPool', 'RuntimeBroker',
           'bootstrap_src', 'output_text', 'ipymini_available', 'find_pythons', 'project_python',
           'python_for', 'venv_env', 'run_file_src']

KERNELS = ('ipykernel', 'ipymini')

def ipymini_available():
    "True when the ipymini package can be imported in this interpreter."
    return importlib.util.find_spec('ipymini') is not None


def project_python(roots=()):
    "The first conventional project-local virtualenv interpreter, or None."
    from pathlib import Path
    for root in L(roots):
        root = Path(root)
        for d in ('.venv', 'venv', 'env', '.env'):
            for b in ('bin/python', 'Scripts/python.exe'):
                if (p := root/d/b).exists(): return str(p)
    return None


def python_for(cwd=None, session=None):
    """The interpreter anything Leela spawns for `cwd` should be inside.

    The folder the work is happening in wins. A workspace can hold several checkouts --
    `/git/repos` exists for exactly that -- and each has its own environment, so keying a
    child to `pool.default_python` put it in the *first* root's venv regardless of which
    project it was for.

    Falling back through discovery rather than stopping at `default_python` matters too: that
    attribute is None until something chooses, so a folder whose venv appeared after the
    workspace was built used to get the bare PATH -- and PATH's `python3` is the system one,
    which is the 3.8 nobody asked for.
    """
    if (py := project_python([cwd]) if cwd else None): return py
    if session is None: return None
    return session.pool.default_python or project_python(session.fs.roots)


def venv_env(python, env=None):
    """`env` (this process's, by default) with `python`'s environment in front of it.

    `VIRTUAL_ENV` is what uv reads and `UV_PROJECT_ENVIRONMENT` keeps `uv run`/`uv sync`
    pointed at this exact env. The PATH prepend is what the console scripts need: a release
    step spelled `nbdev_prepare` is resolved by PATH, and without this it finds whichever
    one the system has rather than the one the project depends on.
    """
    env = dict(os.environ if env is None else env)
    if not python: return env
    bindir = str(Path(python).parent)
    env['VIRTUAL_ENV'] = str(Path(bindir).parent)
    env['UV_PROJECT_ENVIRONMENT'] = env['VIRTUAL_ENV']
    env['PATH'] = bindir + os.pathsep + env.get('PATH', '')
    env.pop('PYTHONHOME', None)
    return env


def find_pythons(roots=()):
    """Interpreters a kernel could be launched under: this one, plus any venv in an open folder.

    What a person means by "which kernel" is usually *which environment* -- the venv with
    their project's dependencies in it, not the one leela happens to be installed in. The
    two are the same only when leela was installed into the project, which is the least
    likely arrangement of the three (pipx, uv tool, and a project venv all separate them).

    Discovery is deliberately shallow: the interpreter running leela, then `bin/python` in
    the usual venv directory names directly under each open folder. Anything else can be
    typed in -- this list is the common case made clickable, not an exhaustive search of
    the disk.
    """
    from pathlib import Path
    from shutil import which
    out, seen = L(), set()

    def add(p, label):
        p = str(p)
        if p in seen or not os.path.exists(p): return
        seen.add(p)
        out.append({'path': p, 'label': label})

    add(sys.executable, 'this one (leela’s own)')
    for r in L(roots):
        r = Path(r)
        for d in ('.venv', 'venv', 'env', '.env'):
            for b in ('bin/python', 'Scripts/python.exe'):
                add(r/d/b, f'{r.name}/{d}')
    for n in ('python3', 'python'):
        if (w := which(n)): add(w, f'{n} on PATH')
    return out


def run_file_src(path, src=None, argv=(), cwd=None):
    """Code that runs a file in the kernel's *own* namespace, with script semantics.

    Three things have to be true at once, and each rules out an obvious alternative:

    - what the script defines must land in the namespace the variable panel is watching,
      which `runpy.run_path` (a fresh dict) and a subprocess (a fresh process) both fail;
    - `__name__` must be `'__main__'`, so a script's `if __name__ == '__main__':` block
      runs -- which it is already, in a kernel, since the user namespace *is* `__main__`;
    - the traceback must point at the file, which is why the source is compiled under
      `path` rather than exec'd as a string.

    `src` is the editor's buffer when it has one, so an unsaved change runs as typed
    instead of silently running the last saved version. The temporaries are named and
    deleted rather than hidden in a function, because a function body would give the
    script its own local scope and every assignment in it would vanish on return.
    """
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

# Bootstrap run silently in a fresh kernel to start its inspector.
#
# It runs inside a function and deletes itself afterwards, so the user's namespace is
# exactly as empty as they left it -- an inspector that shows you its own scaffolding
# in your variable list has failed at its one job. Nothing is returned through the
# namespace either; the port comes back via the registry entry, matched on pid.
#
# Under ipymini we also hand `get_ipython().kernel` to the server as its kernel backend,
# so its HTTP handlers can enter a subshell for concurrent execution.
#
# The engine is dhrishti's. `session_dir`/`agent_session_dir` are what keep its transcripts
# under leela's names rather than dhrishti's defaults -- the exec history a leela kernel
# writes is leela's, and existing `leela_sessions/` directories keep working.
BOOTSTRAP = '''
def _lee_bootstrap():
	import sys, importlib.util
	for _p in {support!r}:
		if _p and _p not in sys.path: sys.path.append(_p)
	# The project venv may contain an older dhrishti. The inspector protocol belongs to
	# this Leela installation, while every other import must remain project-local.
	#
	# Best-effort, because loading by file path is the one thing the ordinary importer
	# does better: a frozen build imports dhrishti out of a zip, where there is no file
	# to point at. A failed pin must leave nothing half-built behind, or the fallback
	# import would find the broken module object in sys.modules and use it.
	try:
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
	                       session_dir='leela_sessions', agent_session_dir='leela_agent_sessions')
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
    import dhrishti
    support = [p for p in sys.path if p and os.path.isabs(p) and os.path.exists(p)]
    dhrishti_init = str(Path(dhrishti.__file__).resolve())
    return BOOTSTRAP.format(name=name, port=port, agent=agent, token=token, support=support,
                            dhrishti_init=dhrishti_init, dhrishti_dir=str(Path(dhrishti_init).parent),
                            ipymini=(kernel == 'ipymini'))


def output_text(outs):
    "Flatten nbformat outputs to plain text -- the terminal rendering, and the agent's view of a run."
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
    'Result of one execute_request: nbformat-shaped outputs plus the shell reply status.'
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
    env = os.environ.copy()
    for name in ('PYTHONHOME', 'PYTHONPATH', 'PYTHONEXECUTABLE', '__PYVENV_LAUNCHER__', 'RESOURCEPATH'):
        env.pop(name, None)
    if python is None and (path := _frozen_pythonpath()): env['PYTHONPATH'] = path
    env['PYTHONUTF8'] = '1'
    return env


def _spec(python=None, name='python3', kernel='ipykernel'):
    "A kernelspec pinned to a specific interpreter, so the kernel lands in *this* venv."
    runtime = _runtime_python(python)
    if kernel == 'ipymini':
        argv = [runtime, '-Xfrozen_modules=off', '-m', 'ipymini', '-f', '{connection_file}']
    else:
        argv = [runtime, '-m', 'ipykernel_launcher', '-f', '{connection_file}']
    metadata = {'supported_encryption': 'curve'} if kernel == 'ipykernel' else {}
    return KernelSpec(argv=argv, display_name=name, language='python', metadata=metadata)


class Kernel:
    "One ipykernel process: execute/complete over jupyter_client, live variables over its in-kernel inspector."

    def __init__(self,
                 cwd=None,              # working directory for the kernel process
                 name=None,             # env label shown in the inspector (default: cwd basename)
                 python=None,           # interpreter to launch (default: this one)
                 inspect=True,          # start an in-kernel inspector
                 agent='restricted',    # agent surface on that server: restricted|readonly|off
                 port=8000,             # base port for the inspector (auto-bumps if taken)
                 kernel='ipykernel'):   # kernel launcher: 'ipykernel' | 'ipymini'
        if kernel not in KERNELS: kernel = 'ipykernel'
        if kernel == 'ipymini' and not ipymini_available():
            warnings.warn("ipymini is unavailable in this interpreter; falling back to ipykernel. "
                          "Install project kernel support from Leela's kernel picker.")
            kernel = 'ipykernel'
        store_attr()
        self.km = self.kc = None
        self._ipc_dir = None
        self.base = None               # inspector base URL, once bootstrapped
        self.boot_error = None         # bootstrap failure text, if the inspector could not start
        self.last_api_error = ''       # latest inspector transport failure, cleared on success
        self._exec_lock = asyncio.Lock()
        self._exec_task = None          # exact coroutine currently consuming kernel channels
        # jupyter_client exposes one shell reply queue. Without serialising consumers,
        # overlapping completion requests can each dequeue and discard the other's reply.
        self._shell_lock = asyncio.Lock()
        self._debug_lock = asyncio.Lock()
        self._debug_seq = 0
        self._debug_thread = None
        self._debug_source = None
        self._debug_sources = {}

    @property
    def kernel_kind(self):
        "Which launcher this kernel was started with: 'ipykernel' or 'ipymini'."
        return self.kernel

    # -- lifecycle ------------------------------------------------------------
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
            # ipykernel supports ZeroMQ IPC. ipymini 0.1.x constructs IPC addresses with
            # TCP-style separators, so it deliberately uses authenticated loopback TCP.
            self._ipc_dir = tempfile.mkdtemp(prefix='lee-k-', dir='/tmp' if os.path.isdir('/tmp') else None)
            manager_kw.update(transport='ipc', ip=os.path.join(self._ipc_dir, 'k'))
        elif os.name != 'nt':
            manager_kw.update(transport='tcp', ip='127.0.0.1')
        elif self.kernel == 'ipykernel':
            # Windows has no ZeroMQ IPC transport. CurveZMQ gives its local TCP channels
            # authenticated encryption instead; the kernelspec explicitly declares it.
            manager_kw['transport_encryption'] = 'required'
        self.km = AsyncKernelManager(**manager_kw)
        self.km._kernel_spec = _spec(self.python, ifnone(self.name, 'python3'), self.kernel)
        cwd = str(self.cwd) if self.cwd else os.getcwd()
        try:
            await self.km.start_kernel(cwd=cwd, env=_kernel_env(self.python))
            client_kw = {}
            # jupyter_client 8.9.1 serialises Curve keys while constructing a client even
            # though the client traits require bytes. Passing the manager's originals also
            # keeps this compatible with fixed releases and is harmless on IPC.
            if getattr(self.km, 'curve_publickey', None) is not None:
                client_kw.update(curve_publickey=self.km.curve_publickey,
                                 curve_secretkey=self.km.curve_secretkey)
            self.kc = self.km.client(**client_kw)
            self.kc.start_channels()
            await self.kc.wait_for_ready(timeout=timeout)
        except BaseException:
            # A failed readiness wait used to leave a child, channels, or IPC directory
            # behind. It also left a cached half-kernel available to control routes.
            await self.shutdown()
            raise
        if self.inspect: await self.bootstrap()
        return self

    async def bootstrap(self):
        "Start the inspector inside the kernel and record its base URL."
        src = bootstrap_src(self.name, self.port, self.agent, True, self.kernel)
        r = await self.execute(src, silent=True, store_history=False)
        if not r.ok:
            self.boot_error = r.error or r.text or 'inspector bootstrap failed'
            return None
        self.base = await self._find_base()
        if self.base is None: self.boot_error = 'inspector started but did not register'
        return self.base

    async def _find_base(self):
        "The registry entry written by our own kernel process, matched on pid."
        for _ in range(40):
            if (e := next((e for e in active() if e.get('pid') == self.pid), None)): return e['base']
            await asyncio.sleep(0.05)
        return None

    @property
    def token(self):
        "Owner token for this kernel's inspector, so the IDE may use its gated endpoints."
        if not self.base: return None
        try: return (reg_dir()/f"token-{self.base.rsplit(':', 1)[-1]}").read_text().strip() or None
        except Exception: return None

    async def api(self, path, params=None, timeout=15):
        """GET this kernel's own inspector, carrying its owner token; None if it has none.

        This is the inspection half of the split: it reaches a background thread inside
        the kernel, so it answers even while a cell is running. Both frontends use it.
        """
        if not self.base: return None
        import httpx2 as httpx
        h = {'X-Dhrishti-Token': t} if (t := self.token) else {}
        try:
            async with httpx.AsyncClient(base_url=self.base, timeout=timeout, headers=h) as c:
                r = await c.get(path, params=params or {})
                r.raise_for_status()
                self.last_api_error = ''
                return r.json()
        except Exception as e:
            self.last_api_error = f'{type(e).__name__}: {e}'
            return None

    def api_sync(self, path, params=None, timeout=30):
        """Synchronous inspector call for model tools running on an agent worker thread."""
        if not self.base: return None
        import httpx2 as httpx
        h = {'X-Dhrishti-Token': t} if (t := self.token) else {}
        try:
            with httpx.Client(base_url=self.base, timeout=timeout, headers=h) as c:
                r = c.get(path, params=params or {})
                r.raise_for_status()
                self.last_api_error = ''
                return r.json()
        except Exception as e:
            self.last_api_error = f'{type(e).__name__}: {e}'
            return None

    async def names(self, scope='live', profile='full'):
        "Every top-level name in this kernel's namespace, or the agent sandbox's. Empty without an inspector."
        base = '/agent/api/rows' if scope == 'isolated' else '/api/rows'
        r = await self.api(base, {'profile': profile, 'sort': 'name'})
        return L(n.get('name', '') for g in (r or {}).get('groups', []) for n in g.get('nodes', []))

    async def interrupt(self):
        "Request cooperative cancellation; callers needing a guarantee should use stop()."
        if self.km: await self.km.interrupt_kernel()

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
        except asyncio.CancelledError:
            return {'ok': True, 'forced': False, 'note': 'cell stopped'}

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

    # -- execution ------------------------------------------------------------
    async def execute(self, code, silent=False, store_history=True, on_output=None, timeout=None,
                      on_debug=None):
        """Run `code` on the shell channel and collect nbformat-shaped outputs.

        `on_output(dict)` is called as each output arrives, so a frontend can stream a
        long cell instead of waiting. Only one execute is in flight at a time: the
        kernel serialises them anyway, and the lock keeps iopub demultiplexing simple.
        """
        if not self.alive: return ExecOutcome(ok=False, error='kernel is not running')
        async with self._exec_lock, self._shell_lock:
            # Lifecycle can change while this request waits behind another execution.
            if not self.alive: return ExecOutcome(ok=False, error='kernel is not running')
            task = asyncio.current_task()
            self._exec_task = task
            try:
                msg_id = self.kc.execute(code, silent=silent, store_history=store_history,
                                         allow_stdin=False)
                outs = await self._collect(msg_id, on_output, timeout, on_debug)
                reply = await self._reply(msg_id, timeout)
            finally:
                if self._exec_task is task: self._exec_task = None
        c = reply.get('content', {}) if reply else {}
        err = None
        if c.get('status') == 'error': err = f"{c.get('ename')}: {c.get('evalue')}"
        elif c.get('status') == 'abort': err = 'aborted'
        if err is None and (e := next((o for o in outs if o['output_type'] == 'error'), None)):
            err = f"{e.get('ename')}: {e.get('evalue')}"
        return ExecOutcome(ok=err is None, execution_count=c.get('execution_count'), outputs=outs, error=err)

    async def _collect(self, msg_id, on_output=None, timeout=None, on_debug=None):
        """Drain iopub for one request, applying Jupyter display-id updates in place.

        IPython's ``display(..., display_id=True).update(...)`` is how Rishi streams a
        growing Markdown document. Treating every update as another output leaves a pile
        of intermediate frames—or only an object repr in simpler clients—instead of the
        final rendered response.
        """
        outs, displays = [], {}
        while True:
            try: msg = await self.kc.get_iopub_msg(timeout=timeout or 0.5)
            except (queue.Empty, asyncio.TimeoutError):
                if not self.alive: break
                continue
            t, c = msg['header']['msg_type'], msg['content']
            # Debug events share IOPub with cell output but are not consistently parented
            # to the execute request. Consume them here—the one owner of this channel—so
            # a second reader cannot steal normal output or the final idle message.
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
                # consecutive writes to one stream belong in one output, as nbformat expects
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
        """Send one Jupyter Debug Protocol/DAP request over ipykernel's control channel."""
        if self.kernel != 'ipykernel':
            raise RuntimeError('cell debugging currently requires an ipykernel runtime')
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
                if not out.get('success', False):
                    raise RuntimeError(out.get('message') or f'debugger rejected {command}')
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
        # debugpy identifies notebook code by a hash-derived temporary source. Dumping all
        # cells lets a step into a class/function defined in an earlier cell navigate to
        # that nearest notebook definition instead of exposing ipykernel's temp file.
        for cell_id, source in notebook_cells:
            dumped = await self.debug_request('dumpCell', {'code': source})
            if (path := dumped.get('body', {}).get('sourcePath')):
                self._debug_sources[path] = cell_id
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
        selected = next((f for f in frames if f.get('id') == int(frame_id or -1)), None)
        selected = selected or (frames[0] if frames else None)
        variables, scopes = [], []
        if selected:
            scope_reply = await self.debug_request('scopes', {'frameId': selected['id']})
            scopes = scope_reply.get('body', {}).get('scopes', [])
            local = next((s for s in scopes if s.get('name', '').lower() == 'locals'),
                         scopes[0] if scopes else None)
            if local and local.get('variablesReference'):
                variables = await self.debug_variables(local['variablesReference'])
        return {'paused': True, 'thread_id': thread_id, 'frame_id': selected.get('id') if selected else None,
                'frames': frames, 'scopes': scopes, 'variables': variables,
                'source': self._debug_source}

    async def debug_evaluate(self, expression, frame_id=None):
        "Evaluate an expression in the selected paused frame—the debugger's exec console."
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
        if command not in {'continue', 'next', 'stepIn', 'stepOut', 'pause'}:
            raise ValueError(f'unknown debug command {command!r}')
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
        """Kernel-side introspection (signature and docstring) for the object at `pos`; '' when unknown.

        IPython answers with terminal colour codes, which are right for a terminal and
        wrong for a browser. Stripped here, once, rather than in each frontend.
        """
        if not self.alive: return ''
        async with self._shell_lock:
            msg_id = self.kc.inspect(code, pos, detail_level=detail)
            r = await self._reply(msg_id)
        c = (r or {}).get('content', {})
        if not c.get('found'): return ''
        return strip_ansi((c.get('data') or {}).get('text/plain') or '')


class GatewayService:
    """One supervised jupygate for all workspace kernels in this Leela process."""

    def __init__(self, port=8787, token=None):
        import secrets
        self.port, self.token, self.server = int(port), token or secrets.token_urlsafe(24), None

    @property
    def url(self): return getattr(self.server, 'url', None) or f'http://127.0.0.1:{self.port}'

    def start(self):
        if self.server is not None: return self
        try:
            from jupygate.core import create_app, serve
        except ImportError as e:
            raise RuntimeError('gateway transport needs `pip install "leela[gateway]"`') from e
        argv = [sys.executable, '-m', 'ipykernel_launcher', '-f', '{connection_file}']
        self.server = serve(create_app(argv=argv, auth_token=self.token), port=self.port, in_thread=True)
        return self

    def stop(self):
        if self.server is not None: self.server.should_exit = True


class GatewayKernel:
    """The ``Kernel`` interface over jupygate + jupyasyncclient instead of local ZMQ.

    Leela still bootstraps its in-kernel inspector, but browser/client reconnects no longer
    own the kernel's ZMQ sockets. One gateway channel set survives every app window.
    """

    def __init__(self, gateway, cwd=None, name=None, python=None, inspect=True,
                 agent='restricted', port=8000, kernel='ipykernel'):
        self.gateway, self.cwd, self.name, self.python = gateway, cwd, name, python
        self.inspect, self.agent, self.port = inspect, agent, port
        self.kernel = kernel if kernel in KERNELS else 'ipykernel'
        if self.kernel == 'ipymini' and not ipymini_available():
            warnings.warn('ipymini not installed; falling back to ipykernel')
            self.kernel = 'ipykernel'
        import uuid
        self.kc, self.base, self.boot_error, self._alive = None, None, None, False
        self.last_api_error = ''
        self._registry_name = f'{self.name or "kernel"}:{uuid.uuid4().hex[:10]}'
        self._exec_lock = asyncio.Lock()
        self._exec_task = None

    @property
    def kernel_kind(self): return self.kernel
    @property
    def alive(self): return self._alive and self.kc is not None
    @property
    def pid(self): return None  # jupygate deliberately does not expose process ids
    @property
    def token(self):
        if not self.base: return None
        try: return (reg_dir()/f"token-{self.base.rsplit(':', 1)[-1]}").read_text().strip() or None
        except Exception: return None

    async def start(self, timeout=60):
        from jupyasyncclient import JupyAsyncKernelClient
        self.gateway.start()
        argv = _spec(self.python, ifnone(self.name, 'python3'), self.kernel).argv
        self.kc = await JupyAsyncKernelClient.connect(self.gateway.url, token=self.gateway.token,
                                                       timeout=timeout, argv=argv,
                                                       env=_kernel_env(self.python),
                                                       cwd=str(self.cwd or os.getcwd()))
        self._alive = True
        if self.inspect: await self.bootstrap()
        return self

    async def bootstrap(self):
        src = bootstrap_src(self._registry_name, self.port, self.agent, True, self.kernel)
        r = await self.execute(src, silent=True, store_history=False)
        if not r.ok:
            self.boot_error = r.error or r.text or 'inspector bootstrap failed'; return None
        for _ in range(60):
            rows = [e for e in active() if e.get('name') == self._registry_name]
            if rows:
                self.base = rows[-1]['base']; return self.base
            await asyncio.sleep(.05)
        self.boot_error = 'inspector started but did not register'
        return None

    async def api(self, path, params=None, timeout=15):
        if not self.base: return None
        import httpx2 as httpx
        headers = {'X-Dhrishti-Token': self.token} if self.token else {}
        try:
            async with httpx.AsyncClient(base_url=self.base, timeout=timeout, headers=headers) as c:
                r = await c.get(path, params=params or {}); r.raise_for_status()
                self.last_api_error = ''
                return r.json()
        except Exception as e:
            self.last_api_error = f'{type(e).__name__}: {e}'
            return None

    def api_sync(self, path, params=None, timeout=30):
        if not self.base: return None
        import httpx2 as httpx
        headers = {'X-Dhrishti-Token': self.token} if self.token else {}
        try:
            with httpx.Client(base_url=self.base, timeout=timeout, headers=headers) as c:
                r = c.get(path, params=params or {}); r.raise_for_status()
                self.last_api_error = ''
                return r.json()
        except Exception as e:
            self.last_api_error = f'{type(e).__name__}: {e}'
            return None

    async def names(self, scope='live', profile='full'):
        base = '/agent/api/rows' if scope == 'isolated' else '/api/rows'
        r = await self.api(base, {'profile': profile, 'sort': 'name'})
        return L(n.get('name', '') for g in (r or {}).get('groups', []) for n in g.get('nodes', []))

    async def execute(self, code, silent=False, store_history=True, on_output=None, timeout=None):
        if not self.alive: return ExecOutcome(ok=False, error='kernel is not running')
        async with self._exec_lock:
            task = asyncio.current_task()
            self._exec_task = task
            run = self.kc.run(code, silent=silent, store_history=store_history)
            outputs = []
            try:
                async for output in run:
                    outputs.append(output)
                    if on_output: on_output(output)
            except Exception as e: return ExecOutcome(ok=False, outputs=outputs, error=str(e))
            finally:
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

    async def stop(self, timeout=2.0):
        "Interrupt through jupygate, then restart its exact kernel if it does not become idle."
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
        except asyncio.CancelledError:
            return {'ok': True, 'forced': False, 'note': 'cell stopped'}

    async def restart(self):
        if not self.kc: return
        self.base = self.boot_error = None
        await self.kc.restart_kernel(); await self.kc.wait_for_ready(timeout=60)
        if self.inspect: await self.bootstrap()

    async def shutdown(self):
        if self.kc:
            try: await self.kc.shutdown_kernel()
            except Exception: pass
            try: await self.kc.aclose()
            except Exception: pass
        self.kc, self.base, self._alive = None, None, False


class RuntimeBroker:
    """Admission control across the kernel pools of every web workspace.

    Multiplexing Jupyter transport does not make Python heaps free. The broker therefore
    imposes one honest process ceiling before a new runtime starts. It never evicts a live
    namespace silently; callers can close a kernel or raise ``LEELA_MAX_KERNELS``.
    """

    def __init__(self, max_kernels=None):
        self.max_kernels = int(max_kernels or os.environ.get('LEELA_MAX_KERNELS', 12))
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

    async def admit(self, pool, key):
        token = (id(pool), key)
        async with self._lock:
            if token in self._reserved or key in pool._starting: return
            if len(self.live) + len(self._reserved) >= self.max_kernels:
                raise RuntimeError(f'kernel limit reached ({self.max_kernels}); close an idle runtime '
                                   'or set LEELA_MAX_KERNELS to a larger value')
            self._reserved.add(token)

    async def release(self, pool, key):
        async with self._lock: self._reserved.discard((id(pool), key))


class KernelPool:
    "The IDE's kernels, keyed by an id the workspace assigns (usually a tab or a folder root)."

    def __init__(self, port=8000, default_kernel='ipykernel', default_python=None, broker=None,
                 transport='direct', gateway=None):
        self.port, self.kernels, self._starting, self.broker = port, {}, {}, None
        self.transport = transport if transport in ('direct', 'gateway') else 'direct'
        self.gateway = gateway
        if broker is not None: broker.register(self)
        self.default_kernel = default_kernel if default_kernel in KERNELS else 'ipykernel'
        # None means "the interpreter leela is running under", which is what `Kernel`
        # already does with it -- so the picker's default needs no special case.
        self.default_python = default_python

    def choose(self, kernel=None, python=False):
        """Set what the *next* kernel starts as. Running kernels are left alone.

        `python=False` rather than `None` as the "leave it" sentinel, because `None` is a
        real choice here: it means leela's own interpreter.

        Nothing is restarted from in here. A namespace is the user's work, and dropping it
        because they opened a picker would be the most expensive thing this IDE could do
        by accident -- the caller restarts, once the person has said so.
        """
        if kernel and kernel in KERNELS: self.default_kernel = kernel
        if python is not False: self.default_python = python
        return {'kernel': self.default_kernel, 'python': self.default_python}

    async def get(self, key, **kw):
        "The kernel for `key`, starting it once even when several browser panels ask together."
        # A manager reports ``has_kernel`` before start() has created its client or finished
        # bootstrap. Never expose that half-started Kernel to another request: it can look
        # alive while ``kc`` is still None, and any execute then crashes in ``kc.execute``.
        if (task := self._starting.get(key)) is not None:
            return await asyncio.shield(task)
        if (k := self.kernels.get(key)) is not None and k.alive: return k
        if self.broker is not None: await self.broker.admit(self, key)

        async def start_one():
            kw.setdefault('kernel', self.default_kernel)
            kw.setdefault('python', self.default_python)
            cls = GatewayKernel if self.transport == 'gateway' else Kernel
            if cls is GatewayKernel:
                if self.gateway is None: self.gateway = GatewayService().start()
                kw['gateway'] = self.gateway
            k = self.kernels[key] = cls(port=self.port, **kw)
            try: return await k.start()
            except BaseException:
                if self.kernels.get(key) is k: self.kernels.pop(key, None)
                raise

        task = self._starting.get(key)
        if task is None:
            task = self._starting[key] = asyncio.create_task(start_one())
        try:
            # A cancelled HTTP completion request must not cancel the kernel startup that
            # the variable panel and editor are sharing.
            return await asyncio.shield(task)
        finally:
            if task.done() and self._starting.get(key) is task:
                self._starting.pop(key, None)
                if self.broker is not None: await self.broker.release(self, key)

    def peek(self, key):
        """A completed live kernel, never the object currently being started.

        Control routes use this without awaiting. Returning the cached object during
        ``start()`` lets Restart/Interrupt call lifecycle methods while ``kc`` is still
        None—the same half-started state that caused the original execute crash.
        """
        if key in self._starting: return None
        k = self.kernels.get(key)
        return k if k is not None and k.alive else None

    async def close(self, key):
        # Do not shut down the manager halfway through start(); wait for the shared task
        # to settle, then close the fully constructed client and remove it.
        if (task := self._starting.get(key)) is not None:
            try: await asyncio.shield(task)
            except BaseException: pass
        if (k := self.kernels.pop(key, None)) is not None: await k.shutdown()

    async def close_all(self):
        tasks = list(self._starting.values())
        if tasks: await asyncio.gather(*[asyncio.shield(task) for task in tasks], return_exceptions=True)
        await asyncio.gather(*[k.shutdown() for k in self.kernels.values()], return_exceptions=True)
        self.kernels.clear()
