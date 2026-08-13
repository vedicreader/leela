"""Real terminals for the IDE, and the lazygit bridge built on them.

A pseudo-terminal is the only honest way to host a full-screen terminal app like lazygit
inside another program: it needs a tty to size itself against, raw keystrokes
including the ones a browser would otherwise eat, and somewhere to put escape
sequences. `Pty` is that -- a command attached to a real pty, read as bytes and
written as bytes, with no interpretation in between. xterm.js on the other end
does the interpreting, which is exactly the division of labour a terminal
emulator expects.

The terminal is *not* inside the `Sandbox`, and pretending otherwise would be a
lie: a shell can go anywhere the user can. The sandbox confines the IDE's own
file API, which is a different promise. What is confined here is the starting
directory (an open root) and, more importantly, *who may connect*: see
`TerminalGate` below, because an unauthenticated pty over a websocket is a
remote shell.

The browser cannot hand control back to a parent terminal, so it needs the PTY and
websocket machinery implemented here.
"""

from __future__ import annotations
import asyncio, fcntl, os, pty, secrets, shlex, shutil, signal, struct, subprocess, sys, termios
from fastcore.all import Path, L
from fastcore.ansi import strip_ansi

__all__ = ['Pty', 'Terminals', 'TerminalGate', 'lazygit_argv', 'gh_auth_argv', 'ToolMissing',
           'LazygitMissing', 'default_shell', 'path_prelude', 'shell_argv',
           'external_terminal_argv', 'EXTERNAL_TERMINALS']

READ_CHUNK = 65536
DEFAULT_SHELL = '/bin/bash'
# Bytes of the child's output kept for `Pty.text`. A build log worth asking about is
# tens of kilobytes; a gigabyte of `yes` is not worth holding on to.
SCROLLBACK = 200_000


class ToolMissing(Exception):
    'A tool the IDE runs is not on PATH. It cannot install one, so it says so instead of failing obscurely.'


class LazygitMissing(ToolMissing):
    'Kept as its own type: `/term/info` reports lazygit separately so the button can be hidden.'


def default_shell():
    "The user's shell, falling back to bash then sh."
    return os.environ.get('SHELL') or (DEFAULT_SHELL if Path(DEFAULT_SHELL).exists() else '/bin/sh')


# Terminals worth handing a project to, best first. A GUI application on macOS is launched
# through `open -a` rather than by running its binary: started directly from a server process it
# inherits this process's session and, for several of these, simply fails to show a window.
EXTERNAL_TERMINALS = (
    ('Kaku', 'kaku'), ('WezTerm', 'wezterm'), ('kitty', 'kitty'), ('Alacritty', 'alacritty'),
    ('Ghostty', 'ghostty'), ('iTerm', 'iterm2'), ('Terminal', None),
)


def shell_argv(shell='', args=(), login=True):
    """How to start the user's shell: which one, and whether as a login shell.

    `-l` is what makes an IDE terminal behave like the one in the dock. On macOS a login shell is
    where PATH and tool setup usually live, so skipping it is how `uv` comes to be missing in
    here and present everywhere else. Explicit `args` replace the flag rather than adding to it,
    because someone who has spelled out the arguments has said what they want.
    """
    exe = str(shell or '').strip() or default_shell()
    extra = [str(a) for a in (args or ())]
    if extra: return [exe, *extra]
    return [exe, '-l'] if login else [exe]


def external_terminal_argv(cwd, command=''):
    """The argv that opens a real terminal application at `cwd`, or None if there is none.

    `command` is a template with `{dir}` in it, for a terminal that wants particular arguments.
    Without one, the first installed entry of `EXTERNAL_TERMINALS` wins -- so this is a button
    that appears when it can work and stays hidden when it cannot, rather than one that fails.
    """
    cwd = str(cwd or Path.home())
    if str(command or '').strip():
        template = str(command).strip()
        parts = shlex.split(template if '{dir}' in template else f'{template} {{dir}}')
        return [cwd if p == '{dir}' else p.replace('{dir}', cwd) for p in parts]
    darwin = sys.platform == 'darwin'
    for app, binary in EXTERNAL_TERMINALS:
        if darwin and Path(f'/Applications/{app}.app').exists():
            return ['open', '-a', app, cwd]
        if binary and (exe := shutil.which(binary)):
            return [exe, cwd] if not darwin else ['open', '-a', app, cwd]
    return None


def path_prelude(py, shell=None):
    """The line that puts a project's venv first on PATH, in the language of the user's shell.

    Setting it in the child's environment is not enough on its own: an interactive shell reads
    its rc file *afterwards*, and `pyenv init -` or conda or asdf then prepends their shims over
    whatever we chose. So the same prepend is typed in once the shell is up, where nothing
    re-orders it.

    Which means it has to be a command *that shell* understands. `export FOO=bar` is not fish,
    which has no `export` at all -- so every terminal under fish opened with
    `fish: Unknown command: export` printed over the first prompt. A leading space keeps the line
    out of history in the shells that honour that, fish included.
    """
    if not py: return ''
    bindir = Path(py).parent
    name = Path(str(shell or default_shell())).name
    if name in ('fish',): return f' set -gx PATH {bindir} $PATH'
    if name in ('csh', 'tcsh'): return f' setenv PATH "{bindir}:$PATH"'
    return f' export PATH="{bindir}:$PATH"'


def lazygit_argv(cwd=None):
    """The argv to run lazygit against `cwd`, or raise `LazygitMissing`.

    Resolved at call time rather than import time: a user who installs lazygit while
    the IDE is open should not have to restart it.
    """
    exe = shutil.which('lazygit')
    if not exe: raise LazygitMissing(
        'lazygit is not installed or not on PATH — see https://github.com/jesseduffield/lazygit#installation')
    return [exe] + (['--path', str(cwd)] if cwd else [])


def gh_auth_argv():
    """The argv for `gh auth login`, or raise `ToolMissing`.

    Authenticating is a conversation -- it asks which host, offers to open a browser, and
    waits for a one-time code to be pasted somewhere else. There is no useful way to do that
    from a panel, and every way of trying ends in a form that reimplements a terminal
    badly. So the button opens the real thing and gets out of the way.
    """
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
        """Spawn the command on a fresh pty.

        `_setctty` is the part that is easy to leave out and painful to debug without.
        A new session alone is not enough: the child must also *claim* the pty as its
        controlling terminal, or the kernel gives it no job control -- `sh` says as much
        on startup, Ctrl-C reaches nothing, and a full-screen app like lazygit cannot
        put the terminal in the mode it needs. `TIOCSCTTY` on fd 0 (already the slave by
        the time `preexec_fn` runs) is what claims it.
        """
        if self.alive: return self
        master, slave = pty.openpty()
        env = dict(os.environ if self.env is None else self.env)
        env.setdefault('TERM', 'xterm-256color')
        env.pop('PYTHONSTARTUP', None)

        def _setctty():
            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)

        try:
            self.proc = subprocess.Popen(
                self.argv, cwd=self.cwd, env=env,
                stdin=slave, stdout=slave, stderr=slave,
                preexec_fn=_setctty, close_fds=True)
            # Typed into the shell rather than set in `env`, because an interactive shell reads
            # its rc file *after* inheriting the environment, and a line like `eval "$(pyenv
            # init -)"` then prepends its shims over whatever we chose. Everything set before
            # the shell starts loses that race; a command run after it does not.
            if self.prelude:
                os.write(master, self.prelude.encode() + b'\n')
        finally:
            os.close(slave)             # the parent must not hold the slave open, or reads never EOF
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
        """Pump the child's output into `on_data(bytes)` until it exits.

        Uses the loop's reader rather than a thread: a pty read is exactly what
        `add_reader` is for, and a thread here would need its own wakeup plumbing to
        stop cleanly when the websocket goes away.
        """
        loop = asyncio.get_running_loop()
        q = asyncio.Queue()

        def _pump():
            try: data = os.read(self.fd, READ_CHUNK)
            except (BlockingIOError, InterruptedError): return
            except OSError: data = b''          # pty closed: the child is gone
            q.put_nowait(data)

        loop.add_reader(self.fd, _pump)
        try:
            while True:
                data = await q.get()
                if not data: break              # EOF
                self._keep(data)
                r = on_data(data)
                if asyncio.iscoroutine(r): await r
        finally:
            try: loop.remove_reader(self.fd)
            except Exception: pass
        # EOF on the pty means the child closed it, not that it has been reaped -- so
        # collect the status before reporting it, or the note reads '[exited None]'.
        if self.proc is not None:
            try: self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired: pass
        self.exit_note = f'[exited {self.proc.returncode}]' if self.proc else '[exited]'

    def _keep(self, data):
        "Retain the tail of the child's output, so it can be read back after it has scrolled past."
        self.scrollback += data
        if len(self.scrollback) > SCROLLBACK: del self.scrollback[:-SCROLLBACK]

    def text(self, n=200):
        """The last `n` lines the child printed, as plain text.

        This is what lets the assistant read a failing build instead of being told about
        one. Two passes of undoing what a terminal does: `strip_ansi` removes the colour
        and cursor escapes, and a bare `\\r` is turned into a newline -- a pty uses it to
        redraw a line in place, so a progress bar would otherwise come back as one
        enormous line.
        """
        s = strip_ansi(bytes(self.scrollback).decode('utf-8', 'replace'))
        # trailing newlines are stripped first, or "the last line" is the empty one after it
        lines = s.replace('\r\n', '\n').replace('\r', '\n').rstrip('\n').split('\n')
        return '\n'.join(lines[-max(1, n):])

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
        if self.fd is not None:
            try: os.close(self.fd)
            except OSError: pass
            self.fd = None

    def state(self):
        return {'pid': self.pid, 'alive': self.alive, 'argv': self.argv, 'cwd': self.cwd,
                'cols': self.cols, 'rows': self.rows, 'exit': self.exit_note}


class Terminals:
    "The IDE's open terminals, keyed by an id the frontend assigns."

    def __init__(self, cwd=None): self.cwd, self.terms = cwd, {}

    def open(self, key, argv=None, cwd=None, env=None, cols=80, rows=24, prelude=''):
        "The terminal for `key`, spawning it on first use."
        if (t := self.terms.get(key)) is not None and t.alive: return t
        t = self.terms[key] = Pty(argv=argv, cwd=cwd or self.cwd, env=env, cols=cols, rows=rows,
                                  prelude=prelude)
        return t.start()

    def get(self, key): return self.terms.get(key)
    def all(self): return L(self.terms.values())

    def states(self):
        """Every terminal this process is holding, *with its key*.

        `Pty.state` cannot say: a pty does not know what it was filed under. The key is the part
        the browser actually needs -- it picks the id for a new terminal, and without knowing
        which ids are taken it reused one, whereupon `open` handed back the *existing* pty and a
        new terminal came up holding an old session's scrollback and running process.
        """
        return [{'id': k, **t.state()} for k, t in self.terms.items()]

    def close(self, key):
        if (t := self.terms.pop(key, None)) is not None: t.kill()

    def close_all(self):
        for t in list(self.terms.values()): t.kill()
        self.terms.clear()


class TerminalGate:
    """Who is allowed to open a terminal, and why the answer is not 'anyone'.

    Two independent checks, because they stop different attacks:

    - **the token.** Websockets are not subject to the same-origin policy, so *any*
      page the user visits can open a socket to `127.0.0.1:5001`. Loopback binding
      alone therefore protects nothing here. A secret the page only gets by being
      served by this app is what makes the connection prove it came from the IDE.
    - **the bind address.** A token is a secret, and secrets leak. Serving a pty on a
      routable interface turns a leak into a remote shell, so that combination is
      refused outright unless the operator asks for it by name.

    The rest of the IDE does not need this: those routes proxy an inspector that has
    its own owner token, and they cannot spawn a shell.
    """

    def __init__(self, host='127.0.0.1', allow_remote=False):
        self.host, self.allow_remote = host, allow_remote
        self.token = secrets.token_urlsafe(24)

    @property
    def loopback(self):
        return self.host in ('127.0.0.1', 'localhost', '::1', '')

    @property
    def enabled(self):
        "Terminals are off on a routable bind address unless explicitly allowed."
        return self.loopback or self.allow_remote

    @property
    def why(self):
        if self.enabled: return ''
        return (f'terminal disabled: the IDE is bound to {self.host}, which is reachable from the '
                'network. Leela supports terminals on loopback addresses only.')

    def check(self, token):
        "Raise unless this connection may have a pty."
        if not self.enabled: raise PermissionError(self.why)
        if not token or not secrets.compare_digest(str(token), self.token):
            raise PermissionError('bad or missing terminal token')
        return True
