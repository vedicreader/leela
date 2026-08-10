"""Named ways to run this project, saved with the project.

The question this answers: *"if I run uvicorn from the terminal, does the variable panel
pick it up?"* -- and the honest answer for a plain `uvicorn app:app` is no. Nothing about
that process is leela's; there is no inspector inside it, so there is nothing to see. What
*is* leela's is the command it starts itself, and `leela.blocks.runtime.devserver` puts an inspector in
that process before the command runs. A run configuration is that command, named and kept.

Three deliberate choices:

- **They live in the project**, at `.leela/runs.json`, next to the code they run. A run
  configuration is a fact about the project ("this is how the API starts"), not a fact
  about the person, and it belongs in the repo where the next person finds it.
- **`cmd` is a command line, not a script path.** `uvicorn app:app --port 8000` is how the
  thing is actually started, and asking someone to translate that into a python file
  before leela will run it is asking them to run something else.
- **`watch` names the module the panel should show**, defaulting to the one the command
  already names (`uvicorn app:app` -> `app`), because the interesting namespace is the
  app's, not the server's.

A process you start yourself can still join in -- it just has to say so, in one line:

    import dhrishti.serving as ds; ds.serve(name='api')
"""

from __future__ import annotations
import json
from dataclasses import dataclass, field
from fastcore.all import Path, L

from ... import Dictable

__all__ = ['Run', 'Runs', 'RUNS_FILE']

RUNS_FILE = '.leela/runs.json'


@dataclass
class Run(Dictable):
    'One named way to start something, under a live inspector.'
    name: str
    cmd: str                                    # 'uvicorn app:app --port 8000', 'python train.py', 'pytest -x'
    cwd: str = ''                               # relative to the project root; '' is the root
    env: dict = field(default_factory=dict)     # non-secret environment values for the child
    env_file: str = ''                          # optional project-relative dotenv file (for example .env.local)
    watch: str = ''                             # module whose namespace to inspect; '' infers it
    inspect: bool = True                        # run it under an inspector at all
    debug: bool = False                         # launch this command through debugpy/DAP
    request: str = 'launch'                     # launch | attach
    program: str = ''                           # project-relative Python file; inferred from cmd when blank
    module: str = ''                            # python -m target
    args: list = field(default_factory=list)
    justMyCode: bool = True
    stopOnEntry: bool = False
    subProcess: bool = True
    host: str = '127.0.0.1'                     # attach is loopback by default
    port: int = 5678
    pathMappings: list = field(default_factory=list)
    django: bool = False
    jinja: bool = False
    gevent: bool = False

    def __post_init__(self):
        if not self.name: self.name = (self.cmd or 'run').split()[0]

    @property
    def label(self): return self.name

    def resolved_cwd(self, root):
        return str(Path(root)/self.cwd) if self.cwd else str(root)

    def resolved_env(self, root):
        "Environment from an optional dotenv file, overlaid by explicit values."
        out = {}
        if self.env_file:
            p = (Path(root)/self.env_file).resolve()
            root = Path(root).resolve()
            if not p.is_relative_to(root): raise ValueError('environment file is outside the project')
            if p.exists():
                for raw in p.read_text(encoding='utf-8', errors='replace').splitlines():
                    line = raw.strip()
                    if not line or line.startswith('#'): continue
                    if line.startswith('export '): line = line[7:].lstrip()
                    key, sep, value = line.partition('=')
                    key = key.strip()
                    if not sep or not key.replace('_', 'a').isalnum() or key[0].isdigit(): continue
                    value = value.strip()
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('\"', "'"):
                        value = value[1:-1]
                    out[key] = value
        out.update({str(k): str(v) for k, v in (self.env or {}).items()})
        return out


class Runs:
    """The run configurations for one project, read from and written back to `.leela/runs.json`.

    Missing file, empty file and unparseable file are all the same thing to a caller: no
    configurations, plus a `note` saying why. A broken JSON file must not stop the IDE from
    opening the project it is in.
    """

    def __init__(self, root=None):
        self.root = Path(root) if root else None
        self.runs = L()
        self.note = ''
        self.load()

    @property
    def path(self): return (self.root/RUNS_FILE) if self.root else None

    def load(self):
        self.runs, self.note = L(), ''
        p = self.path
        if p is None or not p.exists(): return self.runs
        try: d = json.loads(p.read_text())
        except Exception as e:
            self.note = f'{p}: {type(e).__name__}: {e}'
            return self.runs
        items = d.get('runs') if isinstance(d, dict) else d
        for r in (items or []):
            try: self.runs.append(Run(**{k: v for k, v in r.items() if k in Run.__dataclass_fields__}))
            except Exception as e: self.note = f'{p}: bad entry {r!r} ({type(e).__name__}: {e})'
        return self.runs

    def save(self):
        p = self.path
        if p is None: raise ValueError('no project root to save run configurations in')
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({'runs': [r.dict() for r in self.runs]}, indent=2) + '\n')
        return p

    def get(self, name): return next((r for r in self.runs if r.name == name), None)

    def add(self, run, save=True):
        "Add or replace a configuration by name."
        self.runs = L([r for r in self.runs if r.name != run.name]) + L([run])
        if save: self.save()
        return run

    def remove(self, name, save=True):
        r = self.get(name)
        if r is None: return None
        self.runs = self.runs.filter(lambda x: x.name != name)
        if save: self.save()
        return r

    def for_file(self, path):
        """A configuration for a file that has none: run it as a script.

        Not saved. It exists so the run picker always has something to offer for the tab
        that is open, which is what makes the feature discoverable at all -- a picker whose
        only content is "you have no run configurations" teaches nobody anything.
        """
        p = Path(path)
        return Run(name=p.stem, cmd=str(p), cwd='', watch=p.stem)

    def template(self, path=None):
        """A starting file, with whatever the open project makes a plausible first entry.

        The open tab is only used when it is something that can actually be *run*: offering
        `{"cmd": "dialog.ipynb"}` because a notebook happened to be open would be a
        template that fails the first time it is used.
        """
        rs = list(self.runs)
        if not rs:
            py = path if (path and str(path).endswith('.py')) else None
            rs = [self.for_file(py) if py else
                  Run(name='app', cmd='uvicorn app:app --port 8000', watch='app')]
        return {'_help': ['leela run configurations: how this project starts.',
                          'cmd is a command line — `uvicorn app:app --port 8000`, `python train.py`, '
                          '`python -m flask run`. It runs in a process leela puts an inspector in, '
                          'so its module namespace shows up in the variable panel.',
                          'watch names the module to inspect; blank infers it from the command.'],
                'runs': [r.dict() for r in rs]}
