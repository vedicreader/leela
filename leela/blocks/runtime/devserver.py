"Run any command from the IDE under a live inspector in the same process, so its namespace is visible."

from __future__ import annotations
import asyncio, os, re, signal, sys, time, traceback
from collections import deque
from dataclasses import dataclass
from fastcore.all import Path, L, first
from fastcore.xtras import clean_cli_output

from ...core.inspectors import active

__all__ = ['DevServer', 'DevServers']

_URL_HINTS = ('running on', 'listening on', 'http://')
SCROLLBACK = 200_000
#: The child says this once the command it was given has returned; it keeps the inspector up
#: afterwards, so the process outliving the command is not the command still running.
_EXITED = re.compile(r'^\[leela\] command exited \((-?\d+)\)')

def leela_path():
    "Leela's own importable paths, for a child running under some other project's interpreter."
    return [p for p in sys.path if p and os.path.isabs(p) and os.path.exists(p)]

def _boot_src(paths=None):
    """Source that runs `_child` under an interpreter that has never heard of leela.

    `-m` fails because the module is not on that interpreter's path yet. PYTHONPATH *prepends*, so
    leela's copy of fasthtml would shadow the project's own.
    """
    from .support import LEELA_PY
    paths = leela_path() if paths is None else list(paths)
    # Only where the minor version matches, the same condition `_probe` and the kernel bootstrap
    # ask. Leela's path carries bytecode and extension modules built for Leela's interpreter, and a
    # project on another 3.x that extended anyway died on the import rather than on the command.
    return ('import sys\n'
            f'if tuple(sys.version_info[:2]) == {LEELA_PY!r}:\n'
            f' sys.path.extend([p for p in {paths!r} if p not in sys.path])\n'
            'from leela.blocks.runtime.devserver import _child\n'
            '_child(sys.argv[1:])\n')

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
    "One app subprocess running under a live inspector."
    script: str
    cwd: str | None = None
    args: tuple = ()
    name: str | None = None
    port: int = 9000
    max_log: int = 400
    watch: str = ''
    env: dict | None = None
    python: str | None = None   # the project's interpreter; None runs the app in leela's own
    def __post_init__(self):
        self.pty = None
        self.log = deque(maxlen=self.max_log)
        self.base = None
        self.app_url = None
        self.started = self.ended = None
        self._reader = None
        self.command_code = None
        self.screen = bytearray()    # raw terminal bytes, for a viewer that attaches late
        self._subs = set()
    @property
    def proc(self): return self.pty.proc if self.pty else None
    @property
    def alive(self): return self.pty is not None and self.pty.alive
    @property
    def running(self):
        "Whether the *command* is still going. The inspector outlives it, and `alive` follows that."
        return self.alive and self.command_code is None
    @property
    def pid(self): return self.pty.pid if self.pty else None
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
        w = self.watch or infer_watch(self.argv)
        args = ['--port', str(self.port), '--name', self.label,
                *(['--watch', w] if w else []), '--', *self.argv]
        if not self.python or str(self.python) == sys.executable:
            return [sys.executable, '-u', '-m', 'leela.blocks.runtime.devserver', *args]
        # The app belongs in its own project's environment, so that interpreter runs it. Leela's
        # own path is *appended*, so a project's copy of anything leela also ships still wins.
        return [str(self.python), '-u', '-c', _boot_src(), *args]
    def _cwd(self):
        if self.cwd: return str(self.cwd)
        a = self.argv[0]
        from .support import work_dir
        return str(Path(a).parent) if a.endswith('.py') else work_dir()
    async def start(self):
        "Spawn the app on a pty and begin draining it. Returns self once the inspector registers."
        if self.alive: return self
        from ..term.term import Pty
        self.log.clear(); self.screen.clear()
        self.base = self.app_url = self.ended = None
        self.command_code = None
        # A pty rather than a pipe: many apps write colour and progress only on a terminal, and
        # some say nothing at all into a pipe.
        from .kernels import venv_env
        env = venv_env(self.python, {**os.environ, **(self.env or {})})
        self.pty = Pty(self._cmd(), cwd=self._cwd(), env=env)
        self.pty.start()
        self.started = time.time()
        self._reader = asyncio.create_task(self._drain())
        await self._await_inspector()
        return self
    async def _drain(self):
        "Feed the child's terminal to its viewers, and its lines to the ring buffer."
        rest = bytearray()
        def on_data(data):
            self._broadcast(data)
            rest.extend(data)
            while (i := rest.find(b'\n')) >= 0:
                self._line(bytes(rest[:i])); del rest[:i + 1]
        await self.pty.stream(on_data)
        if rest: self._line(bytes(rest))
        self.ended = time.time()
    def _line(self, raw):
        "One output line, kept for `/dev/log`: the escape codes belong to the terminal, not a list."
        s = clean_cli_output(raw.decode('utf-8', 'replace').rstrip('\r\n')).rstrip()
        self.log.append(s)
        if (m := _EXITED.match(s)): self.command_code = int(m.group(1))
        if s.startswith('[leela]') or self.app_url is not None: return
        if any(h in s.lower() for h in _URL_HINTS) and (i := s.find('http://')) >= 0:
            self.app_url = s[i:].split()[0].rstrip('.,')
    def subscribe(self):
        "A queue of terminal frames for one viewer, primed with what has already scrolled by."
        q = asyncio.Queue()
        if self.screen: q.put_nowait(bytes(self.screen))
        self._subs.add(q)
        return q
    def unsubscribe(self, q): self._subs.discard(q)
    def _broadcast(self, data):
        self.screen += data
        if len(self.screen) > SCROLLBACK: del self.screen[:-SCROLLBACK]
        for q in list(self._subs):
            try: q.put_nowait(data)
            except Exception: self._subs.discard(q)
    def write(self, data):
        "Keystrokes into the running app, such as a debugger prompt or ctrl-c."
        if self.pty is not None: self.pty.write(data)
    def resize(self, cols, rows):
        if self.pty is not None: self.pty.resize(cols, rows)
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
        proc = self.proc
        try: os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try: proc.terminate()
            except ProcessLookupError: pass
        for _ in range(max(1, int(grace * 10))):
            if proc.poll() is not None: break
            await asyncio.sleep(0.1)
        else:
            try: os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception: pass
        if self._reader: self._reader.cancel()
        self.base = self.app_url = None
    async def restart(self):
        await self.stop()
        return await self.start()
    def tail(self, n=40): return list(self.log)[-n:]
    def state(self):
        return {'label': self.label, 'script': self.script, 'cmd': ' '.join(self.argv),
            'alive': self.alive, 'running': self.running, 'code': self.command_code,
            'pid': self.pid, 'returncode': self.proc.returncode if self.proc else None,
            'watch': self.watch or infer_watch(self.argv), 'base': self.base, 'app_url': self.app_url,
            'started': self.started, 'ended': self.ended,
            'uptime': (time.time() - self.started) if self.started and self.alive else 0}

class DevServers:
    "The IDE's running apps, keyed by what they run."
    def __init__(self, port=9000): self.port, self.servers = port, {}
    @staticmethod
    def key(script):
        "Resolved path for a script, so the same app opened two ways is one server. A command line keys as itself."
        s = str(script)
        return str(Path(s).resolve()) if s.endswith('.py') and ' ' not in s else s
    async def start(self, script, **kw):
        key = self.key(script)
        # `running`, not `alive`: a server whose command died is what the caller is trying to replace.
        if (s := self.servers.get(key)) is not None and s.running: return s
        if s is not None and s.alive: await s.stop()
        s = self.servers[key] = DevServer(script=key, port=self.port, **kw)
        await s.start()
        return s
    def get(self, script): return self.servers.get(self.key(script))
    def all(self): return L(self.servers.values())
    async def stop(self, script):
        if (s := self.get(script)) is not None: await s.stop()
    async def stop_all(self): await asyncio.gather(*[s.stop() for s in self.servers.values()], return_exceptions=True)

def _script_module(script, name=None):
    "Exec a .py into a real module object *pre-registered in `sys.modules`*, and return it."
    import types
    script = Path(script).resolve()
    modname = name or script.stem
    mod = types.ModuleType(modname)
    mod.__dict__.update({'__name__': '__main__', '__file__': str(script), '__package__': None})
    sys.modules[modname] = mod
    return mod, script

def _watch_module(name):
    "Import the module the panel should watch, before the command that uses it runs. None if the import fails."
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

_RELOAD_SRC = re.compile(r'reload\s*=\s*True')

def _wants_reload(text):
    "Whether a script turns a reloader on in code, which `--reload` in an argv cannot show."
    return bool(_RELOAD_SRC.search(text or ''))

def _warn_reload(why):
    "Say once that a reloader moves the app out of the process the inspector is in."
    if not why: return
    print(f'[leela] a reloader is on ({why}). It runs your app in a child process, so the '
        'inspector here will not see its namespace -- and on a port already in use the reloader '
        'exits, leaving this run with nothing in it. Turn reload off to inspect it.', flush=True)

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
    serve = partial(_serve, session_dir='_leela_sessions', agent_session_dir='_leela_agent_sessions')
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
    code = 0
    if len(cmd) == 1 and cmd[0].endswith('.py'):
        mod, script = _script_module(cmd[0])
        _, base = serve(port=a.port, ns=mod.__dict__, name=label)
        print(f'[leela] inspector live at {base}', flush=True)
        sys.argv = [str(script)]
        sys.path.insert(0, str(script.parent))
        text = script.read_text()
        _warn_reload('this script asks for it' if _wants_reload(text) else '')
        body = lambda: exec(compile(text, str(script), 'exec'), mod.__dict__)
    else:
        _, base = serve(port=a.port, ns={'__name__': '__main__'}, name=label)
        print(f'[leela] inspector live at {base}', flush=True)
        _warn_reload('the command asks for it' if any(c == '--reload' for c in cmd) else '')
        if watch: _watch_module(watch)
        body = lambda: run_command(cmd)
    try: body()
    except KeyboardInterrupt: code = 130
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        if code: traceback.print_exception(e)
    except Exception:
        code = 1
        traceback.print_exc()
    finally:
        print(f'[leela] command exited ({code}); inspector still live', flush=True)
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt: pass

if __name__ == '__main__': _child()
