"Build pipelines and releases: what ships, and the steps that ship it."

from __future__ import annotations
import asyncio, json, os, shlex, time
from dataclasses import dataclass, field
from shutil import which
from fastcore.all import L, Path, first
from fastcore.xtras import strip_ansi
from ...core.envs import EnvStore
from ..term.term import SCROLLBACK, Pty

__all__ = ['Pipeline', 'PipelineError', 'Step', 'env_value', 'resolve_script', 'Release',
           'ReleaseError', 'RELEASE_FILE', 'nbdev_project', 'fastship_project', 'app_project',
           'release_flow', 'default_steps', 'NBDEV_STEPS', 'FASTSHIP_STEPS', 'PLAIN_STEPS',
           'APP_STEPS', 'MATURIN_STEPS', 'CRATE_STEPS', 'rust_project', 'maturin_project']

class PipelineError(RuntimeError):
    pass

def env_value(store, key, default='', secret=False):
    "One value out of the environment store, or `default` when it is unset or unreadable."
    try: return store.get(key, secret=secret) or default
    except Exception: return default

def resolve_script(argv, python=None, env=None):
    "The executable to spawn, accepting either spelling of a hyphenated command."
    name = argv[0]
    spellings = (name, name.replace('_', '-'), name.replace('-', '_'))
    bindir = str(Path(python).parent) if python else ''
    for path in (bindir, (env or os.environ).get('PATH')):
        if not path: continue
        for candidate in spellings:
            if hit := which(candidate, path=path): return [hit, *argv[1:]]
    return argv

@dataclass
class Step:
    "One command in a pipeline."
    id: str
    label: str
    cmd: str
    doc: str = ''
    needs: list = field(default_factory=list)
    argv: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    def dict(self): return {'id': self.id, 'label': self.label, 'cmd': self.cmd,
        'doc': self.doc, 'needs': list(self.needs), 'meta': dict(self.meta)}

class Pipeline:
    "A named sequence of commands for one project: its steps, its state, and its pty."
    FILE = '.leela/pipeline.json'
    KIND = 'pipeline'
    @staticmethod
    def defaults(root): return []
    def __init__(self, root, python=None, env=None):
        self.root = Path(root).expanduser().resolve()
        self.python = python
        self.env = env or EnvStore()
        self.steps = self._load()
        self.results = {}
        self.active = ''
        self.pty = None
        self._pump = None
        self._subs = set()
        self._auto = True
        self.log = bytearray()
    @property
    def path(self): return self.root/self.FILE
    def _load(self):
        try: raw = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError): return self.defaults(self.root)
        steps = raw.get('steps') if isinstance(raw, dict) else raw
        rows = [r for r in (steps or ()) if isinstance(r, dict) and r.get('cmd')]
        out = [Step(id=str(row.get('id') or f'step{i + 1}'),
            label=str(row.get('label') or row.get('id') or 'step'),
            cmd=str(row['cmd']), doc=str(row.get('doc') or ''),
            needs=[str(x) for x in (row.get('needs') or ())],
            argv=[str(x) for x in (row.get('argv') or ())],
            meta=dict(row.get('meta') or {})) for i, row in enumerate(rows)]
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
        found = first(self.steps, lambda s: s.id == str(step_id))
        if found is None: raise PipelineError(f'unknown release step: {step_id}')
        return found
    def needs(self):
        "Every environment key the pipeline names, in the order the steps name them."
        return list(L(self.steps).attrgot('needs').concat().unique())
    def missing(self, step):
        "Keys this step names that dockeasy's store cannot produce."
        try: return [k for k in step.needs if not self.env.get(k)]
        except Exception: return [k for k in step.needs if not os.environ.get(k)]
    def _env(self):
        "The child's environment: this process, the project venv, then `.env` on top."
        from ..runtime.kernels import venv_env
        env = venv_env(self.python)
        try: env.update({k: str(v) for k, v in self.env.values(self.needs()).items()})
        except Exception: pass
        env.setdefault('PYTHONUNBUFFERED', '1')
        return env
    def _row(self, s):
        "One step as the panel sees it: the plan, plus how the last run of it went."
        r = self.results.get(s.id) or {}
        return s.dict() | {
            'status': 'running' if s.id == self.active else (r.get('status') or 'pending'),
            'code': r.get('code'), 'started': r.get('started', 0), 'finished': r.get('finished', 0),
            'missing': self.missing(s),
        }
    def state(self):
        rows = [self._row(s) for s in self.steps]
        failed = first(rows, lambda r: r['status'] == 'failed')
        return {'root': str(self.root), 'kind': self.KIND, 'path': str(self.path),
            'configured': self.path.exists(), 'steps': rows, 'active': self.active,
            'running': bool(self.active), 'auto': self._auto,
            'failed': failed['id'] if failed else '',
            'done': bool(rows) and all(r['status'] in ('passed', 'skipped') for r in rows),
            'needs': self.needs()}
    def subscribe(self):
        "A queue of terminal frames for one viewer, primed with what has already scrolled by."
        q = asyncio.Queue()
        if self.log: q.put_nowait(bytes(self.log))
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
        "Keystrokes into the running step: twine asks for a password."
        if self.pty is not None and self.pty.alive: self.pty.write(data)
    def resize(self, cols, rows):
        if self.pty is not None: self.pty.resize(cols, rows)
    async def start(self, step_id='', auto=True):
        "Run one step, then keep going while they pass. Refuses to start a second one."
        if self.active: raise PipelineError(f'{self.active} is still running')
        self._auto = bool(auto)
        step = self.step(step_id) if step_id else self._next()
        if step is None: raise PipelineError('every step has already run — reset to run them again')
        await self._run(step)
        return self.state()
    def _next(self):
        "The first step that has not passed or been skipped."
        done = ('passed', 'skipped')
        return first(self.steps, lambda s: (self.results.get(s.id) or {}).get('status') not in done)
    def _after(self, step):
        i = [s.id for s in self.steps].index(step.id)
        return self.steps[i + 1] if i + 1 < len(self.steps) else None
    def _resolve(self, argv, env):
        "The executable to spawn, from this pipeline's interpreter."
        return uv_argv(self.root, argv) or resolve_script(argv, self.python, env)
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
        try: self.pty.start()
        except OSError as e:
            self.active = ''
            self.results[step.id] = {'status': 'failed', 'code': None, 'started': int(time.time()),
                'finished': int(time.time()), 'error': str(e)}
            self._broadcast(f'\r\n\x1b[31m{step.cmd}: {e}\x1b[0m\r\n'.encode())
            return
        self._pump = asyncio.create_task(self._drain(step))
    async def _drain(self, step):
        "Pump the pty to every viewer, then record how the step ended and decide what next."
        try: await self.pty.stream(self._broadcast)
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
        if ok and self._auto and (nxt := self._after(step)) is not None: await self._run(nxt)
    def blame(self, checkouts=()):
        "Which of your packages raised in the last failure, with the path rewritten to your checkout."
        from ..stack.packages import blame as attribute
        if not any((self.results.get(s.id) or {}).get('status') == 'failed' for s in self.steps):
            return {}
        return attribute(self.tail(400), checkouts=checkouts)
    def tail(self, lines=80):
        "The end of the transcript as plain text, escapes gone and bare returns made newlines."
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
        "Mark a step done without running it."
        step = self.step(step_id)
        if self.active == step.id: raise PipelineError(f'{step.id} is still running')
        self.results[step.id] = {'status': 'skipped', 'code': None,
            'started': 0, 'finished': int(time.time())}
        return self.state()
    def reset(self):
        "Forget what ran. The commands are unchanged."
        if self.active: raise PipelineError(f'{self.active} is still running')
        self.results.clear()
        self.log.clear()
        self._broadcast(b'\x1b[2J\x1b[H')
        return self.state()


RELEASE_FILE = '.leela/release.json'
ReleaseError = PipelineError

def uv_argv(root, argv):
    "`argv` through `uv run` where uv owns the project, else None."
    root = Path(root)
    if not (root/'uv.lock').exists(): return None
    exe = which('uv')
    if not exe: return None
    # Spelled the way the project spells it: uv runs the project's own script where there is one,
    # and PATH is where another interpreter's copy waits.
    name = argv[0]
    bindir = root/'.venv'/'bin'
    hit = first(n for n in (name, name.replace('_', '-'), name.replace('-', '_'))
                if (bindir/n).exists())
    return [exe, 'run', '--project', str(root), hit or name.replace('_', '-'), *argv[1:]]

def nbdev_project(root):
    "An nbdev project: `settings.ini` for nbdev 2, or `[tool.nbdev]` in `pyproject.toml`."
    root = Path(root)
    try:
        text = (root/'settings.ini').read_text(encoding='utf-8', errors='replace')
        if '[DEFAULT]' in text and any(k in text for k in ('nbs_path', 'lib_name', 'doc_path')):
            return True
    except OSError: pass
    try:
        import tomllib
        with open(root/'pyproject.toml', 'rb') as f: data = tomllib.load(f)
    except (OSError, ValueError): return False
    return 'nbdev' in (data.get('tool') or {}) or 'nbdev' in ((data.get('project') or {}).get('entry-points') or {})

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

FASTSHIP_STEPS = [
    Step('test', 'test', 'python -m pytest -q', 'Run the test suite before anything is published.'),
    Step('changelog', 'changelog', 'ship-changelog',
        'Rewrite CHANGELOG.md from the issues closed since the last release.', ['GITHUB_TOKEN']),
    Step('gh', 'GitHub release', 'ship-gh --no_changelog --no_editor --yes',
        'Commit, push, tag, and create the GitHub release. The changelog step already wrote the notes.',
        ['GITHUB_TOKEN']),
    Step('pypi', 'PyPI release', 'ship-pypi',
        'Build the sdist and wheel, twine check them, then upload.',
        ['TWINE_USERNAME', 'TWINE_PASSWORD']),
    Step('bump', 'bump version', 'ship-bump',
        'Raise the version for the next cycle. fastship bumps after releasing, not before.'),
]

PLAIN_STEPS = [
    Step('test', 'test', 'python -m pytest -q', 'Run the test suite before anything is published.'),
    Step('build', 'build', 'python -m build', 'Build the sdist and wheel into dist/.'),
    Step('gh', 'GitHub release', 'gh release create --generate-notes',
        'Tag and publish a GitHub release.', ['GITHUB_TOKEN']),
    Step('pypi', 'PyPI release', 'python -m twine upload dist/*',
        'Upload the built distributions to PyPI.', ['TWINE_USERNAME', 'TWINE_PASSWORD']),
]

APP_STEPS = [
    Step('app', 'desktop app', 'python tools/build_release.py',
        'Build the platform bundle: a .app and a DMG on macOS, a zipped folder on Windows.'),
    Step('assets', 'attach the app', 'python tools/build_release.py upload',
        'Upload what dist/ holds to the release this version just tagged.', ['GITHUB_TOKEN']),
]

def rust_project(root):
    "A crate: something cargo can build, whether or not Python ever sees it."
    return (Path(root)/'Cargo.toml').exists()

def maturin_project(root):
    "A crate that is also a Python package: maturin builds the wheel, so the release is PyPI's."
    root = Path(root)
    if not rust_project(root): return False
    try:
        import tomllib
        with open(root/'pyproject.toml', 'rb') as f: data = tomllib.load(f)
    except (OSError, ValueError): return False
    backend = str((data.get('build-system') or {}).get('build-backend') or '')
    return backend.startswith('maturin') or 'maturin' in (data.get('tool') or {})

MATURIN_STEPS = [
    Step('test', 'test', 'cargo test', 'Run the crate\'s own tests before anything is published.'),
    Step('wheel', 'build the wheel', 'maturin build --release --out dist',
        'Build here first. A tag that fails to compile on the runners is a tag you have to undo.'),
    Step('ci', 'refresh the workflow', 'maturin generate-ci github -o .github/workflows/CI.yml',
        'maturin writes the matrix: linux, musllinux, macOS, Windows, and the sdist. Rewriting it '
        'from maturin keeps it right when your Python range or targets change.'),
    Step('changelog', 'changelog', 'ship-changelog',
        'Rewrite CHANGELOG.md from the issues closed since the last release.', ['GITHUB_TOKEN']),
    Step('release', 'tag and push', 'ship-release',
        'Tag the version from Cargo.toml and push it. The workflow builds every platform\'s wheel '
        'and publishes them, so nothing is uploaded from here.', ['GITHUB_TOKEN']),
]

CRATE_STEPS = [
    Step('test', 'test', 'cargo test', 'Run the crate\'s tests before anything is published.'),
    Step('clippy', 'clippy', 'cargo clippy --all-targets -- -D warnings',
        'The lints. A crate other people will read is worth the stricter pass.'),
    Step('package', 'package', 'cargo package',
        'Build the .crate the registry would receive, and verify it on its own.'),
    Step('publish', 'publish to crates.io', 'cargo publish',
        'Upload it. A version on crates.io cannot be replaced, only yanked.',
        ['CARGO_REGISTRY_TOKEN']),
]

def fastship_project(root):
    "A Python package fastship releases: a `pyproject.toml`, and not an nbdev project."
    return (Path(root)/'pyproject.toml').exists() and not nbdev_project(root)

def app_project(root):
    "Whether the project packages itself into a desktop app, which `tools/build_release.py` builds."
    root = Path(root)
    return (root/'tools'/'build_release.py').exists() and (root/'setup_app.py').exists()

def release_flow(root):
    "Which release flow this project uses."
    if nbdev_project(root): return 'nbdev'
    if maturin_project(root): return 'maturin'
    if rust_project(root): return 'crate'
    return 'fastship' if fastship_project(root) else 'plain'

def _with_app(steps):
    "The app bundle and its upload, after the last step that publishes and before any that bumps."
    at = [i for i, s in enumerate(steps) if s.id in ('gh', 'pypi')]
    i = max(at) + 1 if at else len(steps)
    return [*steps[:i], *APP_STEPS, *steps[i:]]

_FLOWS = {'nbdev': NBDEV_STEPS, 'fastship': FASTSHIP_STEPS, 'plain': PLAIN_STEPS,
          'maturin': MATURIN_STEPS, 'crate': CRATE_STEPS}

def default_steps(root):
    steps = list(_FLOWS[release_flow(root)])
    return _with_app(steps) if app_project(root) else steps

class Release(Pipeline):
    "The release pipeline: nbdev's commands, fastship's for a package that is not one, else plain."
    FILE = RELEASE_FILE
    KIND = 'release'
    @staticmethod
    def defaults(root): return default_steps(root)
    def state(self):
        flow = release_flow(self.root)
        return super().state() | {'flow': flow, 'nbdev': flow == 'nbdev',
            'fastship': flow == 'fastship', 'app': app_project(self.root)}
