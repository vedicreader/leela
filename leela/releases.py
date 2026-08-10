"""Shipping a release, one step at a time, with the terminal it needs to be believed.

`nbdev_prepare && nbdev_bump_version && nbdev_release_gh && nbdev_pypi` is the whole of an
nbdev release, and typing it as one line is exactly what makes it unpleasant: the chain
stops somewhere in the middle, the scrollback holds four commands' output, and working out
*which* of them failed and whether the version was already bumped is the actual work. A
pipeline that runs the same four commands but keeps their identity -- this step, that exit
code, that output -- turns the same failure into a red box with a retry button next to it.

Three decisions worth stating.

**The steps are a project file, not a hard-coded list.** `.leela/release.json` sits next to
`.leela/runs.json` for the same reason: how this project ships is a fact about the project.
An nbdev project that has never been configured gets the nbdev pipeline as its default,
which is what "understands nbdev projects" means here -- it is a starting point you can
edit, not a special case in the code.

**The values it needs come from dockeasy.** `GITHUB_TOKEN` for the GitHub release and the
twine credentials for PyPI are read through `leela.envs`, which is dockeasy's keychain and
`fastops` dotenv rather than anything Leela stores -- so a token set from a dockeasy script,
from `gheasy`, or from this panel is one value, not three.

**Each step runs on a pseudo-terminal.** `nbdev_prepare` prints progress in place, `uv`
draws a spinner, and twine asks for a password. All three need a tty, and a captured pipe
would turn the first two into noise and hang on the third. The pty is Leela's own `Pty`, so
the browser renders it in the same xterm the shell uses, with the same theme and the same
scrollback.

**Success advances; failure stops.** A green step starts the next one without being asked,
because that is the sequence people were typing anyway. A red one halts the pipeline with
its output on screen: continuing past a failed `nbdev_prepare` to publish to PyPI is not a
convenience, it is a bad release. `skip` exists for the case where the person looking at
the output decides the failure did not matter -- but it is theirs to decide, one press at a
time.
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
from .term import SCROLLBACK, Pty, strip_ansi

__all__ = ['Release', 'ReleaseError', 'Step', 'RELEASE_FILE', 'nbdev_project', 'default_steps']

RELEASE_FILE = '.leela/release.json'
TERM_KEY = 'release'


class ReleaseError(RuntimeError):
    pass


def nbdev_project(root):
    """Is this an nbdev project? Both ways of saying so count.

    Classic nbdev keeps its configuration in `settings.ini`; nbdev 3 also reads
    `[tool.nbdev]` from `pyproject.toml`, which is how every `*easy` package in this
    workspace is laid out -- and a detector that only knew about `settings.ini` would decide
    that none of them were nbdev projects at all. Read from disk rather than from
    `nbdev.config`: nbdev belongs to the project being released, not to Leela.
    """
    root = Path(root)
    try:
        text = (root/'settings.ini').read_text(encoding='utf-8', errors='replace')
        if '[DEFAULT]' in text and any(k in text for k in ('nbs_path', 'lib_name', 'doc_path')):
            return True
    except OSError: pass
    try:
        import tomllib
        with open(root/'pyproject.toml', 'rb') as f: data = tomllib.load(f)
    except (OSError, ValueError, ImportError): return False
    return 'nbdev' in (data.get('tool') or {}) or 'nbdev' in ((data.get('project') or {}).get('entry-points') or {})


@dataclass
class Step:
    """One command in the pipeline.

    `needs` names the environment keys the command cannot work without. It is not
    enforcement -- the command is what fails or succeeds -- it is so the panel can say
    "this needs GITHUB_TOKEN" *before* you watch a release step fail for want of one.
    """
    id: str
    label: str
    cmd: str
    doc: str = ''
    needs: list = field(default_factory=list)

    def dict(self): return {'id': self.id, 'label': self.label, 'cmd': self.cmd,
                            'doc': self.doc, 'needs': list(self.needs)}


NBDEV_STEPS = [
    Step('prepare', 'nbdev_prepare', 'nbdev_prepare',
         'Export the notebooks, run the tests, clean the metadata, rebuild the README.'),
    Step('bump', 'bump version', 'nbdev_bump_version',
         'Raise the version in settings.ini and commit it.'),
    Step('gh', 'GitHub release', 'nbdev_release_gh',
         'Tag the version and create the GitHub release from CHANGELOG.', ['GITHUB_TOKEN']),
    Step('pypi', 'PyPI release', 'nbdev_pypi',
         'Build the wheel and upload it to PyPI.', ['TWINE_USERNAME', 'TWINE_PASSWORD']),
]

PLAIN_STEPS = [
    Step('test', 'test', 'python -m pytest -q', 'Run the test suite before anything is published.'),
    Step('build', 'build', 'python -m build', 'Build the sdist and wheel into dist/.'),
    Step('gh', 'GitHub release', 'gh release create --generate-notes',
         'Tag and publish a GitHub release.', ['GITHUB_TOKEN']),
    Step('pypi', 'PyPI release', 'python -m twine upload dist/*',
         'Upload the built distributions to PyPI.', ['TWINE_USERNAME', 'TWINE_PASSWORD']),
]


def default_steps(root):
    return list(NBDEV_STEPS if nbdev_project(root) else PLAIN_STEPS)


class Release:
    """The pipeline for one project: its steps, where it got to, and the pty it runs on.

    One pipeline per workspace and one step at a time, on purpose. Two releases of the same
    project running at once is never what anyone meant, and a single running step is what
    lets the terminal, the state and the exit code refer to the same thing without anybody
    having to say which.
    """

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
    def path(self): return self.root/RELEASE_FILE

    def _load(self):
        try: raw = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError): return default_steps(self.root)
        steps = raw.get('steps') if isinstance(raw, dict) else raw
        out = []
        for row in steps or ():
            if not isinstance(row, dict) or not row.get('cmd'): continue
            out.append(Step(id=str(row.get('id') or f'step{len(out) + 1}'),
                            label=str(row.get('label') or row.get('id') or 'step'),
                            cmd=str(row['cmd']), doc=str(row.get('doc') or ''),
                            needs=[str(x) for x in (row.get('needs') or ())]))
        return out or default_steps(self.root)

    def save(self, steps):
        "Persist an edited pipeline. Refuses a plan with no runnable command in it."
        rows = [s for s in (steps or ()) if str((s or {}).get('cmd') or '').strip()]
        if not rows: raise ReleaseError('a pipeline needs at least one step with a command')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({'steps': rows}, indent=2) + '\n', encoding='utf-8')
        self.steps = self._load()
        return self.state()

    def reset_plan(self):
        "Back to the default pipeline for this kind of project, without deleting the file."
        self.steps = default_steps(self.root)
        return self.state()

    def step(self, step_id):
        found = next((s for s in self.steps if s.id == str(step_id)), None)
        if found is None: raise ReleaseError(f'unknown release step: {step_id}')
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
        return {'root': str(self.root), 'nbdev': nbdev_project(self.root), 'path': str(self.path),
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
        if self.active: raise ReleaseError(f'{self.active} is still running')
        self._auto = bool(auto)
        step = self.step(step_id) if step_id else self._next()
        if step is None: raise ReleaseError('every step has already run')
        await self._run(step)
        return self.state()

    def _next(self):
        "The first step that has not passed or been skipped."
        return next((s for s in self.steps
                     if (self.results.get(s.id) or {}).get('status') not in ('passed', 'skipped')), None)

    def _after(self, step):
        i = [s.id for s in self.steps].index(step.id)
        return self.steps[i + 1] if i + 1 < len(self.steps) else None

    async def _run(self, step):
        argv = shlex.split(step.cmd)
        if not argv: raise ReleaseError(f'{step.id} has no command to run')
        self.active = step.id
        self.results[step.id] = {'status': 'running', 'code': None,
                                 'started': int(time.time()), 'finished': 0}
        banner = f'\r\n\x1b[1;36m❯ {step.cmd}\x1b[0m\r\n'
        self.pty = Pty(argv=argv, cwd=str(self.root), env=self._env(), cols=100, rows=30)
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
        if self.active == step.id: raise ReleaseError(f'{step.id} is still running')
        self.results[step.id] = {'status': 'skipped', 'code': None,
                                 'started': 0, 'finished': int(time.time())}
        return self.state()

    def reset(self):
        "Forget what ran. The commands are unchanged; only this attempt's history goes."
        if self.active: raise ReleaseError(f'{self.active} is still running')
        self.results.clear()
        self.log.clear()
        self._broadcast(b'\x1b[2J\x1b[H')      # a fresh attempt gets a fresh terminal
        return self.state()
