"Run any command from the IDE under a live inspector in the same process, so its namespace is watchable."

from __future__ import annotations
import asyncio, os, signal, sys, time
from collections import deque
from dataclasses import dataclass
from fastcore.all import Path, L, first

from dhrishti.serving import active

__all__ = ['DevServer', 'DevServers']

_URL_HINTS = ('running on', 'listening on', 'http://')


def split_cmd(cmd):
    "A command line as argv. Accepts a list already split, or a string to split like a shell."
    if not isinstance(cmd, str): return [str(c) for c in cmd]
    import shlex
    return shlex.split(cmd)


def infer_watch(argv):
    "Which module a command is *about*, for the inspector to watch; '' when the caller has to say."
    for a in argv[1:]:
        if a.startswith('-'): continue
        if ':' in a and '/' not in a and not a.endswith('.py'): return a.split(':', 1)[0]
    for a in argv:
        if a.endswith('.py'): return Path(a).stem
    return ''


@dataclass
class DevServer:
    'One app subprocess running under a live inspector.'
    script: str                    # a .py path, or any command line ('uvicorn app:app --port 8000')
    cwd: str | None = None
    args: tuple = ()
    name: str | None = None
    port: int = 9000               # base port for the app's *inspector* (auto-bumps if taken)
    max_log: int = 400
    watch: str = ''                # module whose namespace the panel shows; inferred when blank
    env: dict | None = None        # extra environment for the child

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
    def argv(self): return split_cmd(self.script) + [str(a) for a in self.args]

    @property
    def is_script(self):
        "Whether this is the original shape: one .py file, run as a script."
        a = self.argv
        return len(a) == 1 and a[0].endswith('.py')

    @property
    def label(self):
        if self.name: return self.name
        a = self.argv
        return Path(a[0]).stem if self.is_script else ' '.join(a[:2])

    def _cmd(self):
        # -u so the child's output reaches the log pane as it happens rather than in blocks
        w = self.watch or infer_watch(self.argv)
        return [sys.executable, '-u', '-m', 'leela.blocks.runtime.devserver', '--port', str(self.port),
            '--name', self.label, *(['--watch', w] if w else []), '--', *self.argv]

    def _cwd(self):
        if self.cwd: return str(self.cwd)
        a = self.argv[0]
        return str(Path(a).parent) if a.endswith('.py') else os.getcwd()

    async def start(self):
        "Spawn the app and begin draining its output. Returns self once the inspector registers."
        if self.alive: return self
        self.log.clear(); self.base = self.app_url = None
        self.proc = await asyncio.create_subprocess_exec(
            *self._cmd(), cwd=self._cwd(), env={**os.environ, **(self.env or {})},
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
            if (e := first(active(), lambda e: e.get('pid') == self.pid)):
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
        return {'label': self.label, 'script': self.script, 'cmd': ' '.join(self.argv),
            'alive': self.alive, 'pid': self.pid, 'watch': self.watch or infer_watch(self.argv),
            'base': self.base, 'app_url': self.app_url,
            'uptime': (time.time() - self.started) if self.started and self.alive else 0}


class DevServers:
    "The IDE's running apps, keyed by what they run."

    def __init__(self, port=9000): self.port, self.servers = port, {}

    @staticmethod
    def key(script):
        "Resolved path for a script, so the same app opened two ways is one server; a command line is its own key."
        s = str(script)
        return str(Path(s).resolve()) if s.endswith('.py') and ' ' not in s else s

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

    async def stop_all(self): await asyncio.gather(*[s.stop() for s in self.servers.values()], return_exceptions=True)


# ---------------------------------------------------------------------------
# child entry point: `python -m leela.blocks.runtime.devserver -- <command>`
# ---------------------------------------------------------------------------
def _script_module(script, name=None):
    "Exec a .py into a real module object *pre-registered in `sys.modules`*, and return it."
    # Without the pre-registration, `serve()`'s import string (`app:app`) makes uvicorn build a
    # *second* module object, and requests mutate globals that are not the ones being inspected.
    import types
    script = Path(script).resolve()
    modname = name or script.stem
    mod = types.ModuleType(modname)
    mod.__dict__.update({'__name__': '__main__', '__file__': str(script), '__package__': None})
    sys.modules[modname] = mod
    return mod, script


def _watch_module(name):
    "Import the module the panel should watch, before the command that uses it runs; None if it will not import."
    from dhrishti.serving import watch
    p = Path(f'{name}.py')
    try:
        if p.exists():
            mod, script = _script_module(p, name)
            exec(compile(script.read_text(), str(script), 'exec'), mod.__dict__)
        else:
            from importlib import import_module
            mod = import_module(name)
        watch(mod.__dict__, name)
        print(f'[leela] watching {name}', flush=True)
        return mod
    except Exception as e:
        print(f'[leela] could not watch {name}: {type(e).__name__}: {e}', flush=True)
        return None


def _entry_point(name):
    "An installed console script by name (`uvicorn`, `flask`, `pytest`), as a callable, or None."
    try:
        from importlib.metadata import entry_points
        for ep in entry_points(group='console_scripts'):
            if ep.name == name: return ep.load()
    except Exception: pass
    return None


def run_command(argv):
    "Run `argv` *in this process*, so the inspector shares its namespace."
    import runpy
    argv = [str(a) for a in argv]
    if not argv: raise SystemExit('nothing to run')
    head, rest = argv[0], argv[1:]
    if Path(head).name in ('python', 'python3', sys.executable, Path(sys.executable).name): return run_command(rest)
    if head == '-m':
        if not rest: raise SystemExit('-m needs a module')
        sys.argv = [rest[0], *rest[1:]]
        return runpy.run_module(rest[0], run_name='__main__', alter_sys=True)
    if head.endswith('.py'):
        mod, script = _script_module(head)
        sys.argv = [str(script), *rest]
        sys.path.insert(0, str(script.parent))
        return exec(compile(script.read_text(), str(script), 'exec'), mod.__dict__)
    if (fn := _entry_point(head)) is not None:
        sys.argv = [head, *rest]
        return fn()
    raise SystemExit(f'[leela] cannot run {head!r} in this process — '
        f'write it as `python -m {head} ...` if it is a module')


def _child(argv=None):
    "Run a command under a live inspector, in this process."
    import argparse
    from functools import partial
    from dhrishti.serving import serve as _serve
    # keep dhrishti's transcripts under leela's names, as the kernel bootstrap does
    serve = partial(_serve, session_dir='leela_sessions', agent_session_dir='leela_agent_sessions')

    p = argparse.ArgumentParser(prog='leela-dev')
    p.add_argument('--port', type=int, default=9000, help='base port for the inspector')
    p.add_argument('--name', default=None)
    p.add_argument('--watch', default='', help='module whose namespace the panel should show')
    p.add_argument('cmd', nargs=argparse.REMAINDER,
        help='the command to run, after `--` (a .py, `-m module`, or a console script)')
    a = p.parse_args(argv)
    cmd = [c for c in a.cmd if c != '--']
    if not cmd: raise SystemExit('nothing to run')

    watch = a.watch or infer_watch(cmd)
    sys.path.insert(0, os.getcwd())
    label = a.name or watch or Path(cmd[0]).stem

    # Served straight onto the script's own module, so it is inspectable *while* it executes.
    if len(cmd) == 1 and cmd[0].endswith('.py'):
        mod, script = _script_module(cmd[0])
        _, base = serve(port=a.port, ns=mod.__dict__, name=label)
        print(f'[leela] inspector live at {base}', flush=True)
        sys.argv = [str(script)]
        sys.path.insert(0, str(script.parent))
        body = lambda: exec(compile(script.read_text(), str(script), 'exec'), mod.__dict__)
    else:
        _, base = serve(port=a.port, ns={'__name__': '__main__'}, name=label)
        print(f'[leela] inspector live at {base}', flush=True)
        if any(c == '--reload' for c in cmd):
            print('[leela] --reload runs your app in a child process; the inspector is in '
                'this one and will not see it. Drop --reload to inspect it.', flush=True)
        if watch: _watch_module(watch)
        body = lambda: run_command(cmd)

    try: body()
    except KeyboardInterrupt: pass
    except SystemExit as e:
        if e.code: print(f'[leela] {e}', flush=True)
    finally:
        # The inspector outlives the command: a finished script still has a namespace worth reading.
        print('[leela] command exited; inspector still live', flush=True)
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt: pass


if __name__ == '__main__': _child()
