"""Run a web app from the IDE, with a live inspector attached to it.

A FastHTML (or Flask, or any Python) app started from the editor, running under
`leela.inspect.serve`, so its module namespace shows up in the variable panel as
just another env. You can watch a request handler's globals change while the
app serves traffic -- which is the thing an ordinary debugger cannot do,
because it needs the process stopped.

Nothing new is invented for discovery. `serve()` inside the child registers in
leela's registry, so the IDE finds the inspector by pid exactly the way it
finds a kernel's.
"""

from __future__ import annotations
import asyncio, os, signal, sys, time
from collections import deque
from dataclasses import dataclass
from fastcore.all import Path, L

from .inspect.server import active

__all__ = ['DevServer', 'DevServers']

_URL_HINTS = ('running on', 'listening on', 'http://')


@dataclass
class DevServer:
    'One app subprocess running under a live inspector.'
    script: str
    cwd: str | None = None
    args: tuple = ()
    name: str | None = None
    port: int = 9000               # base port for the app's *inspector* (auto-bumps if taken)
    max_log: int = 400

    def __post_init__(self):
        self.proc = None
        self.log = deque(maxlen=self.max_log)
        self.base = None           # inspector URL
        self.app_url = None        # the app's own URL, scraped from its output
        self.started = None
        self._reader = None

    # -- lifecycle -----------------------------------------------------------
    @property
    def alive(self): return self.proc is not None and self.proc.returncode is None

    @property
    def pid(self): return self.proc.pid if self.proc else None

    @property
    def label(self): return self.name or Path(self.script).stem

    def _cmd(self):
        # -u so the child's output reaches the log pane as it happens rather than in blocks
        return [sys.executable, '-u', '-m', 'leela.devserver', '--port', str(self.port),
                '--name', self.label, self.script, *map(str, self.args)]

    async def start(self):
        "Spawn the app and begin draining its output. Returns self once the inspector registers."
        if self.alive: return self
        self.log.clear(); self.base = self.app_url = None
        self.proc = await asyncio.create_subprocess_exec(
            *self._cmd(), cwd=str(self.cwd or Path(self.script).parent),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            start_new_session=True)          # its own group, so stop() cannot signal the IDE
        self.started = time.time()
        self._reader = asyncio.create_task(self._drain())
        await self._await_inspector()
        return self

    async def _drain(self):
        "Pump the child's combined output into the ring buffer, scraping its URL as it goes."
        assert self.proc and self.proc.stdout
        while True:
            line = await self.proc.stdout.readline()
            if not line: break
            s = line.decode('utf-8', 'replace').rstrip()
            self.log.append(s)
            # Skip our own banner, or the inspector's URL would be mistaken for the app's.
            if s.startswith('[leela]') or self.app_url is not None: continue
            if any(h in s.lower() for h in _URL_HINTS) and (i := s.find('http://')) >= 0:
                self.app_url = s[i:].split()[0].rstrip('.,')

    async def _await_inspector(self, tries=60):
        "Wait for the child's own registry entry, matched on pid."
        for _ in range(tries):
            if not self.alive: return None
            if (e := next((e for e in active() if e.get('pid') == self.pid), None)):
                self.base = e['base']
                return self.base
            await asyncio.sleep(0.1)
        return None

    async def stop(self, grace=3.0):
        "Terminate the whole process group; a web server usually has children of its own."
        if not self.alive: return
        try: os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try: self.proc.terminate()
            except ProcessLookupError: pass
        try: await asyncio.wait_for(self.proc.wait(), grace)
        except asyncio.TimeoutError:
            try: os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
            except Exception: pass
        if self._reader: self._reader.cancel()
        self.base = self.app_url = None

    async def restart(self):
        await self.stop()
        return await self.start()

    def tail(self, n=40): return list(self.log)[-n:]

    def state(self):
        return {'label': self.label, 'script': self.script, 'alive': self.alive, 'pid': self.pid,
                'base': self.base, 'app_url': self.app_url,
                'uptime': (time.time() - self.started) if self.started and self.alive else 0}


class DevServers:
    "The IDE's running apps, keyed by script path."

    def __init__(self, port=9000): self.port, self.servers = port, {}

    @staticmethod
    def key(script):
        "Servers are keyed by resolved path, so the same app opened two ways is one server."
        return str(Path(script).resolve())

    async def start(self, script, **kw):
        key = self.key(script)
        if (s := self.servers.get(key)) is not None and s.alive: return s
        s = self.servers[key] = DevServer(script=key, port=self.port, **kw)
        await s.start()
        return s

    def get(self, script): return self.servers.get(self.key(script))
    def all(self): return L(self.servers.values())

    async def stop(self, script):
        if (s := self.get(script)) is not None: await s.stop()

    async def stop_all(self):
        await asyncio.gather(*[s.stop() for s in self.servers.values()], return_exceptions=True)


# ---------------------------------------------------------------------------
# child entry point: `python -m leela.devserver app.py`
# ---------------------------------------------------------------------------
def _child(argv=None):
    """Run a script under a live inspector, in this process.

    The script is executed inside a real module object that is *pre-registered in
    `sys.modules` under its own name*, and that detail is the whole trick.
    FastHTML's `serve()` hands uvicorn an import string (`app:app`), so uvicorn
    imports the module rather than reusing the one already executed. Without the
    pre-registration that import builds a second module object, and every request
    then mutates globals that are not the ones being inspected -- the panel sits
    there showing a request counter frozen at zero while the app happily serves.

    Registering first means uvicorn's import finds this module, so the dict the
    handlers write to is exactly the dict the inspector is watching.

    `__name__` is still `__main__` so the app's own guard fires and starts the server.
    """
    import argparse, types
    from .inspect.server import serve

    p = argparse.ArgumentParser(prog='leela-dev')
    p.add_argument('script')
    p.add_argument('--port', type=int, default=9000, help='base port for the inspector')
    p.add_argument('--name', default=None)
    p.add_argument('rest', nargs=argparse.REMAINDER)
    a = p.parse_args(argv)

    script = Path(a.script).resolve()
    modname = script.stem
    mod = types.ModuleType(modname)
    mod.__dict__.update({'__name__': '__main__', '__file__': str(script), '__package__': None})
    sys.modules[modname] = mod          # so uvicorn's `import <modname>` returns *this* module

    _, base = serve(port=a.port, ns=mod.__dict__, name=a.name or modname)
    print(f'[leela] inspector live at {base}', flush=True)

    sys.argv = [str(script), *a.rest]
    sys.path.insert(0, str(script.parent))
    try:
        exec(compile(script.read_text(), str(script), 'exec'), mod.__dict__)
    except KeyboardInterrupt: pass
    finally:
        print('[leela] app exited; inspector still live', flush=True)
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt: pass


if __name__ == '__main__': _child()
