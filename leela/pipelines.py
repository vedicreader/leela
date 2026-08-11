"""One command at a time, with the terminal it needs to be believed.

`a && b && c` is how a release or a deploy gets typed, and typing it that way is exactly
what makes it unpleasant: the chain stops somewhere in the middle, the scrollback holds
three commands' output at once, and working out *which* of them failed and what it left
half-done is the actual work. A pipeline runs the same commands but keeps their identity --
this step, that exit code, that output -- so the same failure becomes a red box with a retry
button beside it.

`leela.releases` and `leela.deploys` are the two that exist; both are this class plus a list
of commands and the project file they are saved in.

Three decisions worth stating.

**The steps are a project file, not a hard-coded list.** They live beside `.leela/runs.json`
for the same reason: how a project ships is a fact about the project. What a project gets
before anyone has configured it is a *default*, not a special case in the code -- editable,
and saved the moment it is edited.

**Each step runs on a pseudo-terminal.** `nbdev_prepare` prints progress in place, `uv`
draws a spinner, rsync redraws a percentage, and twine asks for a password. All four need a
tty; a captured pipe turns the first three into noise and hangs on the fourth. The pty is
Leela's own `Pty`, so the browser renders it in the same xterm the shell uses.

**Success advances; failure stops.** A green step starts the next one without being asked,
because that is the sequence someone was typing anyway. A red one halts with its output on
screen: continuing past a failed build to publish, or past a failed tunnel to point DNS at
it, is not a convenience. `skip` exists for when the person reading the output decides the
failure did not matter -- but it is theirs to decide, one press at a time.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import time
from dataclasses import dataclass, field
from pathlib import Path

from .envs import EnvStore
from .blocks.term.term import SCROLLBACK, Pty, strip_ansi

__all__ = ['Pipeline', 'PipelineError', 'Step']


class PipelineError(RuntimeError):
    pass


@dataclass
class Step:
    """One command in a pipeline.

    `needs` names the environment keys the command cannot work without. It is not
    enforcement -- the command is what fails or succeeds -- it is so the panel can say
    "this needs HCLOUD_TOKEN" *before* anyone watches a step fail for want of one.
    """
    id: str
    label: str
    cmd: str
    doc: str = ''
    needs: list = field(default_factory=list)
    # What to actually spawn, when that is not what `cmd` reads as. A step that runs a
    # snippet of Python is a command line nobody would want to read and a quoting problem
    # nobody should have to solve, so it carries its argv and shows `cmd` to the person.
    argv: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def dict(self): return {'id': self.id, 'label': self.label, 'cmd': self.cmd,
                            'doc': self.doc, 'needs': list(self.needs), 'meta': dict(self.meta)}


class Pipeline:
    """A named sequence of commands for one project: its steps, its state, and its pty.

    Subclasses supply two things -- `FILE`, the project file the plan is saved in, and
    `defaults`, the plan to use before anyone has saved one. Everything else is shared,
    because a release and a deploy differ in what they run and in nothing else: both are a
    line someone used to type as `a && b && c`, and both are worth breaking apart for the
    same reason.

    One pipeline per project and one step at a time, on purpose. Two of the same running at
    once is never what anyone meant, and a single running step is what lets the terminal,
    the state and the exit code refer to the same thing without anybody having to say which.
    """

    FILE = '.leela/pipeline.json'
    KIND = 'pipeline'

    @staticmethod
    def defaults(root): return []

    def __init__(self, root, python=None, env=None):
        self.root = Path(root).expanduser().resolve()
        self.python = python
        self.env = env or EnvStore()             # dockeasy's store, read fresh for every step
        self.steps = self._load()
        self.results = {}                        # step id -> {status, code, started, finished}
        self.active = ''                         # the step running right now
        self.pty = None
        self._pump = None
        self._subs = set()
        self._auto = True
        # One transcript for the whole release, not one per step. Each step is a new pty
        # with its own scrollback, so without this a terminal opened during step three
        # would show step three and nothing about the failure in step two -- which is the
        # only thing anybody opens it to read.
        self.log = bytearray()

    # -- the plan --------------------------------------------------------------
    @property
    def path(self): return self.root/self.FILE

    def _load(self):
        try: raw = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError): return self.defaults(self.root)
        steps = raw.get('steps') if isinstance(raw, dict) else raw
        out = []
        for row in steps or ():
            if not isinstance(row, dict) or not row.get('cmd'): continue
            out.append(Step(id=str(row.get('id') or f'step{len(out) + 1}'),
                            label=str(row.get('label') or row.get('id') or 'step'),
                            cmd=str(row['cmd']), doc=str(row.get('doc') or ''),
                            needs=[str(x) for x in (row.get('needs') or ())],
                            argv=[str(x) for x in (row.get('argv') or ())],
                            meta=dict(row.get('meta') or {})))
        return out or self.defaults(self.root)

    def save(self, steps):
        "Persist an edited pipeline. Refuses a plan with no runnable command in it."
        rows = [s for s in (steps or ()) if str((s or {}).get('cmd') or '').strip()]
        if not rows: raise PipelineError('a pipeline needs at least one step with a command')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({'steps': rows}, indent=2) + '\n', encoding='utf-8')
        self.steps = self._load()
        return self.state()

    def reset_plan(self):
        "Back to the default pipeline for this kind of project, without deleting the file."
        self.steps = self.defaults(self.root)
        return self.state()

    def step(self, step_id):
        found = next((s for s in self.steps if s.id == str(step_id)), None)
        if found is None: raise PipelineError(f'unknown release step: {step_id}')
        return found

    # -- environment -----------------------------------------------------------
    def needs(self):
        "Every environment key the pipeline names, in the order the steps name them."
        seen = []
        for s in self.steps:
            for k in s.needs:
                if k not in seen: seen.append(k)
        return seen

    def missing(self, step):
        "Keys this step names that dockeasy's store cannot produce -- the reason to look before running."
        try: return [k for k in step.needs if not self.env.get(k)]
        except Exception: return [k for k in step.needs if not os.environ.get(k)]

    def _env(self):
        """The child's environment: this process, the project venv, then `.env` on top.

        dockeasy resolves each key itself, `os.environ` first and its store second, so a
        value exported before Leela started keeps winning -- the same precedence every other
        dockeasy caller sees, rather than one invented here.
        """
        env = os.environ.copy()
        if self.python:
            bindir = str(Path(self.python).parent)
            venv = str(Path(bindir).parent)
            env['VIRTUAL_ENV'] = venv
            env['UV_PROJECT_ENVIRONMENT'] = venv
            env['PATH'] = bindir + os.pathsep + env.get('PATH', '')
            env.pop('PYTHONHOME', None)
        try: env.update({k: str(v) for k, v in self.env.values(self.needs()).items()})
        except Exception: pass                  # dockeasy is optional; the step may not need it
        env.setdefault('PYTHONUNBUFFERED', '1')
        return env

    # -- state -----------------------------------------------------------------
    def state(self):
        rows = []
        for s in self.steps:
            r = self.results.get(s.id) or {}
            rows.append(s.dict() | {
                'status': 'running' if s.id == self.active else (r.get('status') or 'pending'),
                'code': r.get('code'), 'started': r.get('started', 0), 'finished': r.get('finished', 0),
                'missing': self.missing(s),
            })
        failed = next((r for r in rows if r['status'] == 'failed'), None)
        return {'root': str(self.root), 'kind': self.KIND, 'path': str(self.path),
                'configured': self.path.exists(), 'steps': rows, 'active': self.active,
                'running': bool(self.active), 'auto': self._auto,
                'failed': failed['id'] if failed else '',
                'done': bool(rows) and all(r['status'] in ('passed', 'skipped') for r in rows),
                'needs': self.needs()}

    # -- running ---------------------------------------------------------------
    def subscribe(self):
        """A queue of terminal frames for one viewer, primed with what has already scrolled by.

        Replaying the scrollback is what makes a panel opened *after* a step started show
        the same thing as one that was open the whole time -- and the pump below is the only
        reader of the pty, so a viewer arriving late can never have missed bytes that are
        now unrecoverable.
        """
        q = asyncio.Queue()
        if self.log:
            q.put_nowait(bytes(self.log))
        self._subs.add(q)
        return q

    def unsubscribe(self, q): self._subs.discard(q)

    def _broadcast(self, data):
        self.log += data
        if len(self.log) > SCROLLBACK: del self.log[:-SCROLLBACK]
        for q in list(self._subs):
            try: q.put_nowait(data)
            except Exception: self._subs.discard(q)

    def write(self, data):
        "Keystrokes into the running step -- twine asks for a password, and someone has to answer."
        if self.pty is not None and self.pty.alive: self.pty.write(data)

    def resize(self, cols, rows):
        if self.pty is not None: self.pty.resize(cols, rows)

    async def start(self, step_id='', auto=True):
        "Run one step, then keep going while they pass. Refuses to start a second one."
        if self.active: raise PipelineError(f'{self.active} is still running')
        self._auto = bool(auto)
        step = self.step(step_id) if step_id else self._next()
        if step is None: raise PipelineError('every step has already run')
        await self._run(step)
        return self.state()

    def _next(self):
        "The first step that has not passed or been skipped."
        return next((s for s in self.steps
                     if (self.results.get(s.id) or {}).get('status') not in ('passed', 'skipped')), None)

    def _after(self, step):
        i = [s.id for s in self.steps].index(step.id)
        return self.steps[i + 1] if i + 1 < len(self.steps) else None

    def _resolve(self, argv, env):
        """The executable to spawn, accepting either spelling of a hyphenated command.

        nbdev's console scripts are `nbdev_prepare` in nbdev 2 and `nbdev-prepare` in
        nbdev 3, and every document ever written about releasing an nbdev project uses the
        first. A pipeline that fails with "no such file" because the project upgraded is
        not telling anyone anything they can act on, so both spellings are tried.
        """
        from shutil import which
        name = argv[0]
        path = env.get('PATH')
        for candidate in (name, name.replace('_', '-'), name.replace('-', '_')):
            if which(candidate, path=path): return [candidate, *argv[1:]]
        return argv

    async def _run(self, step):
        argv = list(step.argv) if step.argv else shlex.split(step.cmd)
        if not argv: raise PipelineError(f'{step.id} has no command to run')
        self.active = step.id
        self.results[step.id] = {'status': 'running', 'code': None,
                                 'started': int(time.time()), 'finished': 0}
        banner = f'\r\n\x1b[1;36m❯ {step.cmd}\x1b[0m\r\n'
        env = self._env()
        self.pty = Pty(argv=self._resolve(argv, env), cwd=str(self.root), env=env, cols=100, rows=30)
        self._broadcast(banner.encode())
        try:
            self.pty.start()
        except OSError as e:
            self.active = ''
            self.results[step.id] = {'status': 'failed', 'code': None, 'started': int(time.time()),
                                     'finished': int(time.time()), 'error': str(e)}
            self._broadcast(f'\r\n\x1b[31m{step.cmd}: {e}\x1b[0m\r\n'.encode())
            return
        self._pump = asyncio.create_task(self._drain(step))

    async def _drain(self, step):
        """Pump the pty to every viewer, then record how the step ended and decide what next.

        The pump runs whether or not anyone is watching. A pty nobody reads fills its buffer
        and stops the child mid-write, so "the browser is closed" would otherwise mean "the
        release hangs" -- the failure mode most worth designing out of a background runner.
        """
        try:
            await self.pty.stream(self._broadcast)
        except Exception as e:
            self._broadcast(f'\r\n\x1b[31m{type(e).__name__}: {e}\x1b[0m\r\n'.encode())
        code = self.pty.proc.returncode if self.pty.proc else None
        ok = code == 0
        self.results[step.id] = {'status': 'passed' if ok else 'failed', 'code': code,
                                 'started': (self.results.get(step.id) or {}).get('started', 0),
                                 'finished': int(time.time())}
        self.active = ''
        note = '\x1b[32m✓ ' if ok else '\x1b[31m✗ '
        self._broadcast(f'\r\n{note}{step.label} exited {code}\x1b[0m\r\n'.encode())
        if ok and self._auto and (nxt := self._after(step)) is not None:
            await self._run(nxt)

    def blame(self, checkouts=()):
        """Which of your packages raised in the last failure, and where to open it.

        A pipeline is where the family's code actually runs, so it is where a traceback
        actually appears -- and the useful question about one is never "what does it say"
        but *whose code is that*. `leela.packages` answers it and rewrites the path to the
        checkout this workspace has open, so the fix lands in the repository rather than in
        a copy under `.venv`.
        """
        from .packages import blame as attribute
        if not any((self.results.get(s.id) or {}).get('status') == 'failed' for s in self.steps):
            return {}
        return attribute(self.tail(400), checkouts=checkouts)

    def tail(self, lines=80):
        """The end of the release transcript as plain text, for a summary or for the agent.

        Undoes what a terminal does, the same two ways `Pty.text` does: the escapes go, and
        a bare carriage return becomes a newline so a progress bar is lines rather than one
        enormous one.
        """
        text = strip_ansi(bytes(self.log).decode('utf-8', 'replace'))
        rows = text.replace('\r\n', '\n').replace('\r', '\n').rstrip('\n').split('\n')
        return '\n'.join(rows[-max(1, int(lines)):])

    def stop(self):
        "Stop the pipeline where it is. The step is killed; what it already did stays done."
        self._auto = False
        step_id, self.active = self.active, ''
        if self.pty is not None: self.pty.kill()
        if step_id:
            self.results[step_id] = (self.results.get(step_id) or {}) | {
                'status': 'failed', 'code': None, 'finished': int(time.time())}
            self._broadcast(f'\r\n\x1b[33m{step_id} stopped\x1b[0m\r\n'.encode())
        return self.state()

    def skip(self, step_id):
        "Mark a step done without running it -- the judgement call after reading a failure."
        step = self.step(step_id)
        if self.active == step.id: raise PipelineError(f'{step.id} is still running')
        self.results[step.id] = {'status': 'skipped', 'code': None,
                                 'started': 0, 'finished': int(time.time())}
        return self.state()

    def reset(self):
        "Forget what ran. The commands are unchanged; only this attempt's history goes."
        if self.active: raise PipelineError(f'{self.active} is still running')
        self.results.clear()
        self.log.clear()
        self._broadcast(b'\x1b[2J\x1b[H')      # a fresh attempt gets a fresh terminal
        return self.state()
