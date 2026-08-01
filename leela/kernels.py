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
"""

from __future__ import annotations
import asyncio, os, sys, queue
from dataclasses import dataclass, field
from fastcore.all import store_attr, ifnone, L
from fastcore.ansi import strip_ansi
from jupyter_client.manager import AsyncKernelManager
from jupyter_client.kernelspec import KernelSpec

from .inspect.server import reg_dir, active

__all__ = ['ExecOutcome', 'Kernel', 'KernelPool', 'bootstrap_src', 'output_text']

# Bootstrap run silently in a fresh kernel to start its inspector.
#
# It runs inside a function and deletes itself afterwards, so the user's namespace is
# exactly as empty as they left it -- an inspector that shows you its own scaffolding
# in your variable list has failed at its one job. Nothing is returned through the
# namespace either; the port comes back via the registry entry, matched on pid.
BOOTSTRAP = '''
def _lee_bootstrap():
	import leela.inspect.server as ls
	return ls.serve_in_kernel(name={name!r}, port={port!r}, agent={agent!r}, token={token!r})
try: _lee_bootstrap()
finally: del _lee_bootstrap
'''


def bootstrap_src(name=None, port=8000, agent='restricted', token=True):
    "The bootstrap cell source for a kernel that should host an inspector."
    return BOOTSTRAP.format(name=name, port=port, agent=agent, token=token)


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


def _spec(python=None, name='python3'):
    "A kernelspec pinned to a specific interpreter, so the kernel lands in *this* venv."
    return KernelSpec(argv=[python or sys.executable, '-m', 'ipykernel_launcher', '-f', '{connection_file}'],
                      display_name=name, language='python')


class Kernel:
    "One ipykernel process: execute/complete over jupyter_client, live variables over its in-kernel inspector."

    def __init__(self,
                 cwd=None,              # working directory for the kernel process
                 name=None,             # env label shown in the inspector (default: cwd basename)
                 python=None,           # interpreter to launch (default: this one)
                 inspect=True,          # start an in-kernel inspector
                 agent='restricted',    # agent surface on that server: restricted|readonly|off
                 port=8000):            # base port for the inspector (auto-bumps if taken)
        store_attr()
        self.km = self.kc = None
        self.base = None               # inspector base URL, once bootstrapped
        self.boot_error = None         # bootstrap failure text, if the inspector could not start
        self._exec_lock = asyncio.Lock()

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
        self.km = AsyncKernelManager(kernel_name='python3')
        self.km._kernel_spec = _spec(self.python, ifnone(self.name, 'python3'))
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
        src = bootstrap_src(self.name, self.port, self.agent, True)
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

    def __init__(self, port=8000): self.port, self.kernels = port, {}

    async def get(self, key, **kw):
        "The kernel for `key`, starting it on first use."
        if (k := self.kernels.get(key)) is not None and k.alive: return k
        k = self.kernels[key] = Kernel(port=self.port, **kw)
        await k.start()
        return k

    def peek(self, key): return self.kernels.get(key)

    async def close(self, key):
        if (k := self.kernels.pop(key, None)) is not None: await k.shutdown()

    async def close_all(self):
        await asyncio.gather(*[k.shutdown() for k in self.kernels.values()], return_exceptions=True)
        self.kernels.clear()
