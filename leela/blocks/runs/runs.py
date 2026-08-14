"""Named ways to run this project, saved at `.leela/runs.json`.

`leela.blocks.runtime.devserver` puts a dhrishti inspector in the process before the command
runs; a process started by hand can join in with `dhrishti.serving.serve(name=...)`.
"""

from __future__ import annotations
import json
from dataclasses import dataclass, field
from fastcore.all import Path, L, first

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

    def resolved_cwd(self, root): return str(Path(root)/self.cwd) if self.cwd else str(root)

    def resolved_env(self, root):
        "Environment from an optional dotenv file, overlaid by explicit values."
        from dotenv import dotenv_values
        out = {}
        if self.env_file:
            p = (Path(root)/self.env_file).resolve()
            if not p.is_relative_to(Path(root).resolve()):
                raise ValueError('environment file is outside the project')
            out = {k: v for k, v in dotenv_values(p).items() if v is not None}
        out.update({str(k): str(v) for k, v in (self.env or {}).items()})
        return out


class Runs:
    "The run configurations for one project; a broken file yields none plus a `note` saying why."

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
        try: d = p.read_json()
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
        p.mk_write(json.dumps({'runs': [r.dict() for r in self.runs]}, indent=2) + '\n')
        return p

    def get(self, name): return first(self.runs, lambda r: r.name == name)

    def add(self, run, save=True):
        "Add or replace a configuration by name."
        self.runs = self.runs.filter(lambda r: r.name != run.name) + [run]
        if save: self.save()
        return run

    def remove(self, name, save=True):
        r = self.get(name)
        if r is None: return None
        self.runs = self.runs.filter(lambda x: x.name != name)
        if save: self.save()
        return r

    def for_file(self, path):
        "An unsaved configuration for a file that has none: run it as a script."
        p = Path(path)
        return Run(name=p.stem, cmd=str(p), cwd='', watch=p.stem)

    def template(self, path=None):
        "A starting file, seeded from the open tab when that tab is something runnable."
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
