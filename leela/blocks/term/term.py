"Real terminals for the IDE, and the lazygit bridge built on them."

from __future__ import annotations
import asyncio, fcntl, os, pty, secrets, shlex, shutil, signal, struct, subprocess, sys, termios
from fastcore.all import Path, L, store_attr
from fastcore.xtras import clean_cli_output

__all__ = ['Pty', 'Terminals', 'TerminalGate', 'lazygit_argv', 'gh_auth_argv', 'ToolMissing',
           'LazygitMissing', 'default_shell', 'path_prelude', 'shell_argv',
           'external_terminal_argv', 'EXTERNAL_TERMINALS']

READ_CHUNK = 65536
DEFAULT_SHELL = '/bin/bash'
SCROLLBACK = 200_000

class ToolMissing(Exception):
    "A tool the IDE runs is not on PATH."

class LazygitMissing(ToolMissing):
    "Its own type because `/term/info` reports lazygit separately, so the button can be hidden."

def default_shell():
    "The user's shell, falling back to bash then sh."
    return os.environ.get('SHELL') or (DEFAULT_SHELL if Path(DEFAULT_SHELL).exists() else '/bin/sh')

EXTERNAL_TERMINALS = (('Kaku', 'kaku'), ('WezTerm', 'wezterm'), ('kitty', 'kitty'),
    ('Alacritty', 'alacritty'), ('Ghostty', 'ghostty'), ('iTerm', 'iterm2'), ('Terminal', None))

def shell_argv(
    shell='',
    args=(),
    login=True,
):
    "How to start the user's shell."
    exe = str(shell or '').strip() or default_shell()
    extra = [str(a) for a in (args or ())]
    if extra: return [exe, *extra]
    return [exe, '-l'] if login else [exe]

def external_terminal_argv(
    cwd,
    command='',
):
    "The argv that opens a real terminal application at `cwd`, or None if none is installed."
    cwd = str(cwd or Path.home())
    if template := str(command or '').strip():
        parts = shlex.split(template if '{dir}' in template else f'{template} {{dir}}')
        return [cwd if p == '{dir}' else p.replace('{dir}', cwd) for p in parts]
    darwin = sys.platform == 'darwin'
    for app, binary in EXTERNAL_TERMINALS:
        if darwin and Path(f'/Applications/{app}.app').exists(): return ['open', '-a', app, cwd]
        if binary and (exe := shutil.which(binary)): return ['open', '-a', app, cwd] if darwin else [exe, cwd]
    return None

def path_prelude(py, shell=None):
    "The line that puts a project's venv first on PATH, in the language of the user's shell."
    if not py: return ''
    bindir = Path(py).parent
    name = Path(str(shell or default_shell())).name
    if name == 'fish': return f' set -gx PATH {bindir} $PATH'
    if name in ('csh', 'tcsh'): return f' setenv PATH "{bindir}:$PATH"'
    return f' export PATH="{bindir}:$PATH"'

def lazygit_argv(cwd=None):
    "The argv to run lazygit against `cwd`, or raise `LazygitMissing`. Resolved at call time, not."
    exe = shutil.which('lazygit')
    if not exe: raise LazygitMissing(
        'lazygit is not installed or not on PATH — see https://github.com/jesseduffield/lazygit#installation')
    return [exe] + (['--path', str(cwd)] if cwd else [])

def gh_auth_argv():
    "The argv for `gh auth login`, or raise `ToolMissing`."
    exe = shutil.which('gh')
    if not exe: raise ToolMissing(
        'the GitHub CLI is not installed or not on PATH — see https://cli.github.com')
    return [exe, 'auth', 'login']

class Pty:
    "One command on a pseudo-terminal: bytes in, bytes out, and a size."
    def __init__(self, argv=None, cwd=None, env=None, cols=80, rows=24, prelude=''):
        self.argv = list(argv) if argv else [default_shell()]
        self.cwd = str(cwd) if cwd else None
        self.env = env
        self.prelude = str(prelude or '')
        self.cols, self.rows = cols, rows
        self.proc = self.fd = None
        self._reader = None
        self.exit_note = ''
        self.scrollback = bytearray()
    @property
    def alive(self): return self.proc is not None and self.proc.poll() is None
    @property
    def pid(self): return self.proc.pid if self.proc else None
    def start(self):
        "Spawn the command on a fresh pty."
        if self.alive: return self
        master, slave = pty.openpty()
        env = dict(os.environ if self.env is None else self.env)
        env.setdefault('TERM', 'xterm-256color')
        env.pop('PYTHONSTARTUP', None)
        def _setctty():
            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)
        try:
            self.proc = subprocess.Popen(self.argv, cwd=self.cwd, env=env, stdin=slave,
                stdout=slave, stderr=slave, preexec_fn=_setctty, close_fds=True)
            if self.prelude: os.write(master, self.prelude.encode() + b'\n')
        finally:
            os.close(slave)
        self.fd = master
        os.set_blocking(self.fd, False)
        self.resize(self.cols, self.rows)
        return self
    def resize(self, cols, rows):
        "Tell the child its window size, so full-screen apps redraw at the right dimensions."
        self.cols, self.rows = max(1, int(cols)), max(1, int(rows))
        if self.fd is None: return
        try: fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack('HHHH', self.rows, self.cols, 0, 0))
        except OSError: pass
    def write(self, data):
        "Send keystrokes to the child. `data` is bytes exactly as the terminal produced them."
        if self.fd is None or not self.alive: return 0
        if isinstance(data, str): data = data.encode('utf-8', 'replace')
        try: return os.write(self.fd, data)
        except OSError: return 0
    async def stream(self, on_data):
        "Pump the child's output into `on_data(bytes)` until it exits."
        loop = asyncio.get_running_loop()
        q = asyncio.Queue()
        fd = self.fd
        if fd is None:
            self.exit_note = self.exit_note or '[exited]'
            return
        def _pump():
            if self.fd is None: q.put_nowait(b''); return
            try: data = os.read(fd, READ_CHUNK)
            except (BlockingIOError, InterruptedError): return
            except OSError: data = b''
            q.put_nowait(data)
        loop.add_reader(fd, _pump)
        self._reader = (loop, fd, q)
        try:
            while True:
                data = await q.get()
                if not data: break
                self._keep(data)
                r = on_data(data)
                if asyncio.iscoroutine(r): await r
        finally:
            self._reader = None
            try: loop.remove_reader(fd)
            except Exception: pass
        if self.proc is not None:
            try: self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired: pass
        self.exit_note = f'[exited {self.proc.returncode}]' if self.proc else '[exited]'
    def _keep(self, data):
        "Retain the tail of the child's output, so it can be read back after it has scrolled past."
        self.scrollback += data
        if len(self.scrollback) > SCROLLBACK: del self.scrollback[:-SCROLLBACK]
    def text(self, n=200):
        "The last `n` lines the child printed, rendered as they appear on screen."
        s = clean_cli_output(bytes(self.scrollback).decode('utf-8', 'replace'))
        return '\n'.join(s.rstrip('\n').split('\n')[-max(1, n):])
    def kill(self, grace=2.0):
        "Terminate the whole process group -- a shell usually has children of its own."
        if self.proc is not None and self.proc.poll() is None:
            try: os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                try: self.proc.terminate()
                except ProcessLookupError: pass
            try: self.proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                try: os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                except Exception: pass
        self._unwatch()
        if self.fd is not None:
            try: os.close(self.fd)
            except OSError: pass
            self.fd = None
    def _unwatch(self):
        "Unregister the reader before the fd closes, and tell the stream the output has ended."
        if (reader := self._reader) is None: return
        self._reader = None
        loop, fd, q = reader
        def stop():
            try: loop.remove_reader(fd)
            except Exception: pass
            q.put_nowait(b'')
        try: here = asyncio.get_running_loop() is loop
        except RuntimeError: here = False
        try:
            if here: stop()
            else: loop.call_soon_threadsafe(stop)
        except Exception: pass
    def state(self):
        return dict(pid=self.pid, alive=self.alive, argv=self.argv, cwd=self.cwd, cols=self.cols,
            rows=self.rows, exit=self.exit_note)

class Terminals:
    "The IDE's open terminals, keyed by an id the frontend assigns."
    def __init__(self, cwd=None): self.cwd, self.terms = cwd, {}
    def open(self, key, argv=None, cwd=None, env=None, cols=80, rows=24, prelude=''):
        "The terminal for `key`, spawning it on first use."
        if (t := self.terms.get(key)) is not None and t.alive: return t
        t = Pty(argv=argv, cwd=cwd or self.cwd, env=env, cols=cols, rows=rows, prelude=prelude)
        self.terms[key] = t
        return t.start()
    def get(self, key): return self.terms.get(key)
    def all(self): return L(self.terms.values())
    def states(self):
        "Every terminal this process is holding, with its key -- which `Pty.state` cannot know."
        return [{'id': k, **t.state()} for k, t in self.terms.items()]
    def close(self, key):
        if (t := self.terms.pop(key, None)) is not None: t.kill()
    def close_all(self):
        for t in list(self.terms.values()): t.kill()
        self.terms.clear()

class TerminalGate:
    "Who is allowed to open a terminal."
    def __init__(self, host='127.0.0.1', allow_remote=False):
        store_attr()
        self.token = secrets.token_urlsafe(24)
    @property
    def loopback(self): return self.host in ('127.0.0.1', 'localhost', '::1', '')
    @property
    def enabled(self):
        "Terminals are off on a routable bind address unless explicitly allowed."
        return self.loopback or self.allow_remote
    @property
    def why(self):
        if self.enabled: return ''
        return (f'terminal disabled: the IDE is bound to {self.host}, which is reachable from the network. '
            'Leela supports terminals on loopback addresses only.')
    def check(self, token):
        "Raise unless this connection may have a pty."
        if not self.enabled: raise PermissionError(self.why)
        if not token or not secrets.compare_digest(str(token), self.token): raise PermissionError('bad or missing terminal token')
        return True
