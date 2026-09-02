"Real terminals for the IDE, and the lazygit bridge built on them."

from __future__ import annotations
import asyncio, os, secrets, shlex, shutil, signal, subprocess, sys, time
from fastcore.all import Path, L, first, store_attr
from fastcore.xtras import clean_cli_output
from ptymini.core import PtySession

__all__ = ['Pty', 'Terminals', 'TerminalGate', 'lazygit_argv', 'gh_auth_argv', 'ToolMissing',
           'LazygitMissing', 'default_shell', 'path_prelude', 'shell_argv',
           'external_terminal_argv', 'EXTERNAL_TERMINALS']

#: A frame carries everything the ring gathered since the last one, up to this: a websocket frame
#: costs a WKWebView about 140 times what its own bytes do.
MAX_FRAME = 65536
#: What the ring holds. Headroom, not history: `stream` keeps the transcript in `Pty.scrollback`,
#: and this is how far ptymini's reader thread may run ahead of a slow socket before it drops bytes.
RING = 1_000_000
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
    "The argv to run lazygit against `cwd`, or raise `LazygitMissing`. Resolved at call time, not import."
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

def _kids():
    "Pids of this process's direct children. `ps` because ptymini keeps its child's pid to itself."
    # `-A`, or BSD ps lists only what shares this process's terminal, and a bundled app has none.
    try: out = subprocess.run(['ps', '-A', '-o', 'pid=,ppid='], capture_output=True, text=True, timeout=2).stdout
    except Exception: return set()
    me, rows = str(os.getpid()), (r.split() for r in out.splitlines())
    return {int(a) for a, b in (r for r in rows if len(r) == 2) if b == me}

class Pty:
    "One command on a pseudo-terminal: bytes in, bytes out, and a size."
    def __init__(self, argv=None, cwd=None, env=None, cols=80, rows=24, prelude=''):
        self.argv = list(argv) if argv else [default_shell()]
        self.cwd = str(cwd) if cwd else None
        self.env = env
        self.prelude = str(prelude or '')
        self.cols, self.rows = cols, rows
        self.sess = self.pid = None
        self._reading, self._off = False, 0
        self.exit_note = ''
        self.scrollback = bytearray()
    @property
    def alive(self): return self.sess is not None and self.sess.alive
    @property
    def exit_code(self): return self.sess.exit_code if self.sess is not None else None
    @property
    def attached(self):
        "Whether a socket is already streaming this pty. The IDE shows one view of a terminal."
        return self._reading
    def start(self):
        "Spawn the command on a fresh pty. Needs a running loop: the ring wakes its readers on one."
        if self.alive: return self
        env = dict(os.environ if self.env is None else self.env)
        env.setdefault('TERM', 'xterm-256color')
        env.pop('PYTHONSTARTUP', None)
        # Nothing else of ours can spawn between the two counts: `start` never awaits.
        before = _kids()
        self.sess = PtySession(self.argv, cwd=self.cwd, env=env, rows=self.rows, cols=self.cols,
                               buffer_bytes=RING)
        self.pid = first(sorted(_kids() - before))
        self._off = 0
        if self.prelude: self.sess.write(self.prelude.encode() + b'\n')
        return self
    def resize(self, cols, rows):
        "Tell the child its window size, so full-screen apps redraw at the right dimensions."
        self.cols, self.rows = max(1, int(cols)), max(1, int(rows))
        if self.sess is not None: self.sess.resize(self.rows, self.cols)
    def write(self, data):
        "Send keystrokes to the child. `data` is bytes exactly as the terminal produced them."
        if not self.alive: return 0
        if isinstance(data, str): data = data.encode('utf-8', 'replace')
        try: self.sess.write(data)
        except OSError: return 0
        return len(data)
    async def stream(self, on_data):
        "Pump the child's output into `on_data(bytes)` until it exits."
        # One reader a terminal: two views of one pty would each answer half the keystrokes, and the
        # offset this keeps is what lets a later view carry on where this one stopped.
        if self.attached: raise RuntimeError('this terminal already has a reader')
        if (s := self.sess) is None:
            self.exit_note = self.exit_note or '[exited]'
            return
        self._reading, pending = True, bytearray()
        try:
            while True:
                data, self._off, _ = s.read_from(self._off)
                pending += data
                if not pending:
                    if not s.alive: break
                    await s.wait_change(seen_end=self._off)
                    continue
                # Whatever the ring gathered while the last frame was in flight goes in this one.
                frame = bytes(pending[:MAX_FRAME]); del pending[:MAX_FRAME]
                self._keep(frame)
                r = on_data(frame)
                if asyncio.iscoroutine(r): await r
        finally: self._reading = False
        self.exit_note = f'[exited {s.exit_code}]' if s.exit_code is not None else '[exited]'
    def _keep(self, data):
        "Retain the tail of the child's output, so it can be read back after it has scrolled past."
        self.scrollback += data
        if len(self.scrollback) > SCROLLBACK: del self.scrollback[:-SCROLLBACK]
    def text(self, n=200):
        "The last `n` lines the child printed, rendered as they appear on screen."
        s = clean_cli_output(bytes(self.scrollback).decode('utf-8', 'replace'))
        return '\n'.join(s.rstrip('\n').split('\n')[-max(1, n):])
    def kill(self, grace=2.0):
        "Terminate the whole process group: ptymini signals it, and a shell has children of its own."
        if (s := self.sess) is None or not s.alive: return
        try: s.kill(signal.SIGTERM)
        except ProcessLookupError: return
        try: asyncio.get_running_loop().call_later(grace, self._force)
        except RuntimeError:
            end = time.monotonic() + grace
            while s.alive and time.monotonic() < end: time.sleep(.02)
            self._force()
    def _force(self):
        if self.alive:
            try: self.sess.kill(signal.SIGKILL)
            except ProcessLookupError: pass
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
        "Every terminal this process is holding, with its key, which `Pty.state` cannot know."
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
