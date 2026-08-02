"""Managed ipykernels, each hosting its own leela inspector.

This is the pivot away from `get_ipython()`. A notebook tab owns a `Kernel`: a
real ipykernel process driven over `jupyter_client`, which the IDE talks to on
*two* channels, deliberately split:

- **execution** goes down the kernel's shell channel, so exec-strip code and
  notebook cells share one serialised queue, stream their output back over
  iopub, and are interruptible like any cell.
- **inspection** goes over HTTP to a `leela.inspect` server started *inside* that
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
import asyncio, importlib.util, os, sys, queue, warnings
from dataclasses import dataclass, field
from fastcore.all import store_attr, ifnone, L
from fastcore.ansi import strip_ansi
from jupyter_client.manager import AsyncKernelManager
from jupyter_client.kernelspec import KernelSpec

from .inspect.server import reg_dir, active

__all__ = ['ExecOutcome', 'Kernel', 'KernelPool', 'bootstrap_src', 'output_text', 'ipymini_available',
           'find_pythons', 'run_file_src']

KERNELS = ('ipykernel', 'ipymini')

def ipymini_available():
    "True when the ipymini package can be imported in this interpreter."
    return importlib.util.find_spec('ipymini') is not None


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


def run_file_src(path, src=None, argv=()):
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
    return ('import sys as _lee_sys\n'
            f'_lee_code = compile({src!r}, {str(path)!r}, "exec")\n'
            '_lee_argv = _lee_sys.argv\n'
            f'_lee_sys.argv = [{str(path)!r}, *{list(argv)!r}]\n'
            'try: exec(_lee_code)\n'
            'finally:\n'
            '    _lee_sys.argv = _lee_argv\n'
            '    del _lee_sys, _lee_code, _lee_argv\n')

# Bootstrap run silently in a fresh kernel to start its inspector.
#
# It runs inside a function and deletes itself afterwards, so the user's namespace is
# exactly as empty as they left it -- an inspector that shows you its own scaffolding
# in your variable list has failed at its one job. Nothing is returned through the
# namespace either; the port comes back via the registry entry, matched on pid.
#
# Under ipymini we also stash a reference to `get_ipython().kernel` on the inspect
# server module, so its HTTP handlers can enter a subshell for concurrent execution.
BOOTSTRAP = '''
def _lee_bootstrap():
	import leela.inspect.server as ls
	r = ls.serve_in_kernel(name={name!r}, port={port!r}, agent={agent!r}, token={token!r})
	if {ipymini!r}:
		try:
			from IPython import get_ipython
			ls._kernel_backend = getattr(get_ipython(), 'kernel', None)
		except Exception: ls._kernel_backend = None
	return r
try: _lee_bootstrap()
finally: del _lee_bootstrap
'''


def bootstrap_src(name=None, port=8000, agent='restricted', token=True, kernel='ipykernel'):
    "The bootstrap cell source for a kernel that should host an inspector."
    return BOOTSTRAP.format(name=name, port=port, agent=agent, token=token,
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
            parts.append(d.get('text/plain') or next((f'[{k}]' for k in d), ''))
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


def _spec(python=None, name='python3', kernel='ipykernel'):
    "A kernelspec pinned to a specific interpreter, so the kernel lands in *this* venv."
    if kernel == 'ipymini':
        argv = [python or sys.executable, '-Xfrozen_modules=off', '-m', 'ipymini', '-f', '{connection_file}']
    else:
        argv = [python or sys.executable, '-m', 'ipykernel_launcher', '-f', '{connection_file}']
    return KernelSpec(argv=argv, display_name=name, language='python')


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
            warnings.warn("ipymini not installed; falling back to ipykernel. "
                          "Install with `pip install \"leela[ipymini]\"`.")
            kernel = 'ipykernel'
        store_attr()
        self.km = self.kc = None
        self.base = None               # inspector base URL, once bootstrapped
        self.boot_error = None         # bootstrap failure text, if the inspector could not start
        self._exec_lock = asyncio.Lock()

    @property
    def kernel_kind(self):
        "Which launcher this kernel was started with: 'ipykernel' or 'ipymini'."
        return self.kernel

    # -- lifecycle ------------------------------------------------------------
    @property
    def alive(self): return self.km is not None and self.km.has_kernel

    @property
    def pid(self):
        "OS pid of the kernel process, or None."
        p = getattr(getattr(self.km, 'provisioner', None), 'process', None)
        return getattr(p, 'pid', None)

    async def start(self, timeout=60):
        "Launch the kernel, wait for it to answer, then bootstrap its inspector."
        self.km = AsyncKernelManager(kernel_name=self.kernel if self.kernel == 'ipymini' else 'python3')
        self.km._kernel_spec = _spec(self.python, ifnone(self.name, 'python3'), self.kernel)
        cwd = str(self.cwd) if self.cwd else os.getcwd()
        await self.km.start_kernel(cwd=cwd)
        self.kc = self.km.client()
        self.kc.start_channels()
        try: await self.kc.wait_for_ready(timeout=timeout)
        except RuntimeError:
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
        import httpx
        h = {'X-Leela-Token': t} if (t := self.token) else {}
        try:
            async with httpx.AsyncClient(base_url=self.base, timeout=timeout, headers=h) as c:
                r = await c.get(path, params=params or {})
                r.raise_for_status()
                return r.json()
        except Exception:
            return None

    async def names(self, scope='live', profile='full'):
        "Every top-level name in this kernel's namespace, or the agent sandbox's. Empty without an inspector."
        base = '/agent/api/rows' if scope == 'isolated' else '/api/rows'
        r = await self.api(base, {'profile': profile, 'sort': 'name'})
        return L(n.get('name', '') for g in (r or {}).get('groups', []) for n in g.get('nodes', []))

    async def interrupt(self):
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

    # -- execution ------------------------------------------------------------
    async def execute(self, code, silent=False, store_history=True, on_output=None, timeout=None):
        """Run `code` on the shell channel and collect nbformat-shaped outputs.

        `on_output(dict)` is called as each output arrives, so a frontend can stream a
        long cell instead of waiting. Only one execute is in flight at a time: the
        kernel serialises them anyway, and the lock keeps iopub demultiplexing simple.
        """
        if not self.alive: return ExecOutcome(ok=False, error='kernel is not running')
        async with self._exec_lock:
            msg_id = self.kc.execute(code, silent=silent, store_history=store_history,
                                     allow_stdin=False)
            outs = await self._collect(msg_id, on_output, timeout)
            reply = await self._reply(msg_id, timeout)
        c = reply.get('content', {}) if reply else {}
        err = None
        if c.get('status') == 'error': err = f"{c.get('ename')}: {c.get('evalue')}"
        elif c.get('status') == 'abort': err = 'aborted'
        if err is None and (e := next((o for o in outs if o['output_type'] == 'error'), None)):
            err = f"{e.get('ename')}: {e.get('evalue')}"
        return ExecOutcome(ok=err is None, execution_count=c.get('execution_count'), outputs=outs, error=err)

    async def _collect(self, msg_id, on_output=None, timeout=None):
        "Drain iopub for one request, until its idle status. Foreign messages are skipped, not consumed as ours."
        outs = []
        while True:
            try: msg = await self.kc.get_iopub_msg(timeout=timeout or 0.5)
            except (queue.Empty, asyncio.TimeoutError):
                if not self.alive: break
                continue
            if (msg.get('parent_header') or {}).get('msg_id') != msg_id: continue
            t, c = msg['header']['msg_type'], msg['content']
            if t == 'status':
                if c.get('execution_state') == 'idle': break
            elif t == 'clear_output': outs.clear()
            elif o := self._as_output(t, c):
                # consecutive writes to one stream belong in one output, as nbformat expects
                if (o['output_type'] == 'stream' and outs and outs[-1].get('output_type') == 'stream'
                        and outs[-1].get('name') == o['name']): outs[-1]['text'] += o['text']
                else: outs.append(o)
                if on_output: on_output(o)
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

    async def complete(self, code, pos):
        "Completions at `pos` in the `{from, matches}` shape both frontends already consume."
        if not self.alive: return {'from': pos, 'matches': []}
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
        msg_id = self.kc.inspect(code, pos, detail_level=detail)
        r = await self._reply(msg_id)
        c = (r or {}).get('content', {})
        if not c.get('found'): return ''
        return strip_ansi((c.get('data') or {}).get('text/plain') or '')


class KernelPool:
    "The IDE's kernels, keyed by an id the workspace assigns (usually a tab or a folder root)."

    def __init__(self, port=8000, default_kernel='ipykernel', default_python=None):
        self.port, self.kernels = port, {}
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
        "The kernel for `key`, starting it on first use."
        if (k := self.kernels.get(key)) is not None and k.alive: return k
        kw.setdefault('kernel', self.default_kernel)
        kw.setdefault('python', self.default_python)
        k = self.kernels[key] = Kernel(port=self.port, **kw)
        await k.start()
        return k

    def peek(self, key): return self.kernels.get(key)

    async def close(self, key):
        if (k := self.kernels.pop(key, None)) is not None: await k.shutdown()

    async def close_all(self):
        await asyncio.gather(*[k.shutdown() for k in self.kernels.values()], return_exceptions=True)
        self.kernels.clear()
