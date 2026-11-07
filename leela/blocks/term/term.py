"Real terminals for the IDE, and the lazygit bridge built on them."

from __future__ import annotations
import asyncio, errno, os, pty, secrets, shlex, shutil, signal, subprocess, sys, termios, time
from fastcore.all import Path, L, first, store_attr
from fastcore.xtras import clean_cli_output

__all__ = ['Pty', 'Terminals', 'TerminalGate', 'lazygit_argv', 'gh_auth_argv', 'ToolMissing',
           'LazygitMissing', 'NoPython', 'own_python', 'bundle_env', 'default_shell', 'path_prelude', 'shell_argv',
           'external_terminal_argv', 'EXTERNAL_TERMINALS', 'colorfgbg']

#: A frame carries everything the ring gathered since the last one, up to this: a websocket frame
#: costs a WKWebView about 140 times what its own bytes do.
MAX_FRAME = 65536
#: What the ring holds while no socket is reading. Headroom, not history: `stream` keeps the
#: transcript in `Pty.scrollback`.
RING = 1_000_000
DEFAULT_SHELL = '/bin/bash'
SCROLLBACK = 200_000

class ToolMissing(Exception):
    "A tool the IDE runs is not on PATH."

class LazygitMissing(ToolMissing):
    "Its own type because `/term/info` reports lazygit separately, so the button can be hidden."

class NoPython(ToolMissing):
    "A frozen app whose bundle has no helper Python."

def colorfgbg(mode):
    "The `COLORFGBG` for a resolved theme mode, or `None` for anything else, which leaves the inherited value alone."
    return {'light': '0;15', 'dark': '15;0'}.get(mode) if isinstance(mode, str) else None

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

#: Home, clear the screen, clear the scrollback: the echoed prelude goes, and the first prompt is the first line.
CLEAR = r"printf '\033[H\033[2J\033[3J'"

def path_prelude(py, shell=None):
    "The line that puts a project's venv first on PATH, in the language of the user's shell, then clears its own echo."
    if not py: return ''
    bindir = Path(py).parent
    name = Path(str(shell or default_shell())).name
    if name == 'fish': return f" set -gx PATH {bindir} $PATH; printf '\\e[H\\e[2J\\e[3J'"
    if name in ('csh', 'tcsh'): return f' setenv PATH "{bindir}:$PATH"; {CLEAR}'
    return f' export PATH="{bindir}:$PATH"; {CLEAR}'

def lazygit_argv(cwd=None):
    "The argv to run lazygit against `cwd`, or raise `LazygitMissing`. Resolved at call time, not import."
    exe = shutil.which('lazygit')
    if not exe: raise LazygitMissing(
        'lazygit is not installed or not on PATH. See https://github.com/jesseduffield/lazygit#installation')
    return [exe] + (['--path', str(cwd)] if cwd else [])

def gh_auth_argv():
    "The argv for `gh auth login`, or raise `ToolMissing`."
    exe = shutil.which('gh')
    if not exe: raise ToolMissing(
        'the GitHub CLI is not installed or not on PATH. See https://cli.github.com')
    return [exe, 'auth', 'login']

def own_python():
    "Python for a child that runs Leela's code or the pty shim: the bundle's helper when frozen."
    from ..runtime.kernels import runtime_python
    exe = runtime_python()
    # py2app sets `sys.executable` to the helper itself; py2exe sets it to `Leela.exe`, which runs no `-c`.
    if getattr(sys, 'frozen', False) and not Path(exe).name.lower().startswith('python'):
        raise NoPython('no Python to start this: the app bundle has no helper interpreter; reinstall Leela')
    return exe

def bundle_env():
    "What the helper needs in its environment to find its standard library, since `-c` runs after startup. Empty outside a bundle."
    from ..runtime.kernels import frozen_pythonpath
    if not (path := frozen_pythonpath()): return {}
    return {'PYTHONHOME': str(Path(sys.executable).resolve().parent.parent/'Resources'), 'PYTHONPATH': path}

#: Names in `LEELA_PTY_DROP` are removed before the exec, so the user's shell never inherits the bundle's paths.
_PTY_BOOT = r'''
import fcntl, os, sys, termios
fcntl.ioctl(0, termios.TIOCSCTTY, 0)
for k in os.environ.pop('LEELA_PTY_DROP', '').split(','): os.environ.pop(k, None)
os.execvpe(sys.argv[1], sys.argv[1:], os.environ)
'''

class PtySession:
    "A command on its own pty and process group, read on the loop into a ring a late viewer replays from."
    def __init__(self, argv, cwd, env, rows, cols, buffer_bytes, keep_bundle=False):
        self.loop = asyncio.get_running_loop()
        self.buf, self.pending = bytearray(), bytearray()
        self.end, self.limit = 0, buffer_bytes
        self.changed = asyncio.Event()
        self.eof = False
        self.stopping = False
        self.escalation = None
        exe = sys.executable
        if getattr(sys, 'frozen', False):
            from kunda.pythons import strip_bundle
            exe, bundle = own_python(), bundle_env()
            drop = {} if keep_bundle else {'LEELA_PTY_DROP': ','.join(bundle)}
            env = {**strip_bundle(dict(env)), **bundle, **drop}
        self.fd, slave = pty.openpty()
        try:
            termios.tcsetwinsize(slave, (rows, cols))
            self.proc = subprocess.Popen([exe, '-c', _PTY_BOOT, *argv],
                stdin=slave, stdout=slave, stderr=slave, cwd=cwd, env=env, start_new_session=True)
        except BaseException:
            os.close(self.fd)
            raise
        finally: os.close(slave)
        self.pid = self.proc.pid
        os.set_blocking(self.fd, False)
        self.loop.add_reader(self.fd, self._read)
    @property
    def alive(self): return self.proc.poll() is None
    @property
    def exit_code(self): return self.proc.poll()
    def _read(self):
        for _ in range(256):
            try: data = os.read(self.fd, MAX_FRAME)
            except BlockingIOError: break
            except OSError: data = b''   # EIO once the slave is gone; anything else is as final
            if not data:
                self.close()
                break
            self.buf.extend(data)
            self.end += len(data)
            if len(self.buf) > self.limit: del self.buf[:-self.limit]
        self.changed.set()
    def close(self):
        if self.eof: return
        self.eof = True
        self.loop.remove_reader(self.fd)
        self.loop.remove_writer(self.fd)
        try: os.close(self.fd)
        except OSError: pass
        self.changed.set()
        self.proc.poll()
    def read_from(self, off):
        start = self.end - len(self.buf)
        return bytes(self.buf[max(0, off-start):]), self.end, max(0, start-off)
    async def wait_change(self, seen_end, timeout=None):
        "Until the ring moves past `seen_end`, the pty closes, or `timeout` passes."
        self.changed.clear()
        if self.end != seen_end or self.eof: return
        try: await asyncio.wait_for(self.changed.wait(), timeout)
        except asyncio.TimeoutError: pass
    def resize(self, rows, cols):
        if not self.eof: termios.tcsetwinsize(self.fd, (rows, cols))
    def write(self, data):
        if self.eof: raise OSError(errno.EIO, 'terminal closed')
        self.pending.extend(data)
        self._write()
    def _write(self):
        while self.pending:
            try: n = os.write(self.fd, self.pending)
            except BlockingIOError:
                self.loop.add_writer(self.fd, self._write)
                return
            except OSError:
                self.close()
                return
            del self.pending[:n]
        self.loop.remove_writer(self.fd)
    def kill(self, sig):
        try: os.killpg(self.pid, sig)
        except (ProcessLookupError, PermissionError): pass   # gone, or only zombies left
    @property
    def group_alive(self):
        "Whether anything in the owned group is still running: the leader reaped first, then a null signal."
        self.proc.poll()
        try: os.killpg(self.pid, 0)
        except ProcessLookupError: return False
        except Exception: return True   # EPERM or anything odd: assume alive, and let the deadline decide
        return True
    def _escalate(self, end):
        self.escalation = None
        if not self.group_alive: return
        if time.monotonic() >= end:
            self.kill(signal.SIGKILL)
            return
        self.escalation = self.loop.call_later(.02, self._escalate, end)

class Pty:
    "One command on a pseudo-terminal: bytes in, bytes out, and a size."
    def __init__(self, argv=None, cwd=None, env=None, cols=80, rows=24, prelude='', keep_bundle=False):
        self.keep_bundle = keep_bundle   # a child that runs on the helper itself needs its paths; a shell does not
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
        # a parent with no terminal leaves none, '' or dumb; any other TERM was set on purpose
        if env.get('TERM', '') in ('', 'dumb'): env['TERM'] = 'xterm-256color'
        if not env.get('COLORTERM'): env['COLORTERM'] = 'truecolor'   # xterm.js draws 24-bit colour
        env.pop('PYTHONSTARTUP', None)
        self.sess = PtySession(self.argv, cwd=self.cwd, env=env, rows=self.rows, cols=self.cols,
                               buffer_bytes=RING, keep_bundle=self.keep_bundle)
        self.pid = self.sess.pid
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
        self._reading, pending, gone = True, bytearray(), None
        try:
            while True:
                data, self._off, _ = s.read_from(self._off)
                pending += data
                if not pending:
                    if s.eof:
                        while s.alive: await asyncio.sleep(.01)
                        break
                    # A leader that exits while a background job holds the slave sends no EOF: give
                    # its trailing output half a second, then release the fd rather than wait on it.
                    if not s.alive:
                        gone = gone or time.monotonic() + .5
                        if time.monotonic() >= gone:
                            s.close()
                            continue
                    await s.wait_change(seen_end=self._off, timeout=.25)
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
        "Signal the owned group, including workers that outlive its leader."
        if (s := self.sess) is None: return
        if grace <= 0:
            if s.escalation: s.escalation.cancel()
            s.kill(signal.SIGKILL)
            return
        if s.stopping: return
        s.kill(signal.SIGTERM)
        s.stopping = True
        try:
            asyncio.get_running_loop()
            s._escalate(time.monotonic() + grace)
        except RuntimeError:
            end = time.monotonic() + grace
            while s.group_alive and time.monotonic() < end: time.sleep(.02)
            if s.group_alive: s.kill(signal.SIGKILL)
    def state(self):
        return dict(pid=self.pid, alive=self.alive, argv=self.argv, cwd=self.cwd, cols=self.cols,
            rows=self.rows, exit=self.exit_note)

class Terminals:
    "The IDE's open terminals, keyed by an id the frontend assigns."
    def __init__(self, cwd=None): self.cwd, self.terms = cwd, {}
    def open(self, key, argv=None, cwd=None, env=None, cols=80, rows=24, prelude=''):
        "The terminal for `key`, spawning it on first use."
        if (t := self.terms.get(key)) is not None and t.alive: return t
        t = Pty(argv=argv, cwd=cwd or self.cwd, env=env, cols=cols, rows=rows, prelude=prelude).start()
        self.terms[key] = t
        return t
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
        if not token or not secrets.compare_digest(str(token).encode(), self.token.encode()): raise PermissionError('bad or missing terminal token')
        return True
