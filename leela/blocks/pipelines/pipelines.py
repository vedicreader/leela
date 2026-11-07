"Build pipelines and releases: what ships, and the steps that ship it. pullup's, under `.leela/`."

from __future__ import annotations

from fastcore.xtras import Path
from pullup.pipeline import Pipeline as _Pipeline, PipelineError, Release as _Release, resolve_script

from ..stack.packages import FAMILY

#: Only what Leela adds. Everything else pullup already publishes, and a caller that wants
#: `default_steps` or `resolve_script` imports it from `pullup` rather than through here.
__all__ = ['Pipeline', 'Release', 'PipelineError', 'ReleaseError', 'STATE_DIR', 'RELEASE_FILE', 'has_venv']

#: Where Leela keeps what it writes into somebody's project.
STATE_DIR = '.leela'
RELEASE_FILE = f'{STATE_DIR}/release.json'
ReleaseError = PipelineError

def has_venv(root):
    "Whether `root` has its own `.venv`. `uv run` makes one where there is none."
    return (Path(root)/'.venv').is_dir()

class _Leela:
    "What a pipeline of Leela's differs in: where its plan lives, whose stack it blames, and that it never makes a venv."
    def __init__(self, root, python=None, env=None): super().__init__(root, python, env, STATE_DIR)
    def _resolve(self, argv, env): return super()._resolve(argv, env) if has_venv(self.root) else resolve_script(argv, self.python, env)
    def blame(self, checkouts=()): return super().blame(checkouts, FAMILY)

class Pipeline(_Leela, _Pipeline): pass
class Release(_Leela, _Release): pass
