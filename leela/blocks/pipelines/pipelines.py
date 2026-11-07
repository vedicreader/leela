"Build pipelines and releases: what ships, and the steps that ship it. pullup's, under `.leela/`."

from __future__ import annotations

from fastcore.xtras import Path
from pullup.pipeline import Pipeline as _Pipeline, PipelineError, Release as _Release

from ..runtime.kernels import NoVenv, python_project
from ..stack.packages import FAMILY

#: Only what Leela adds. Everything else pullup already publishes, and a caller that wants
#: `default_steps` or `resolve_script` imports it from `pullup` rather than through here.
__all__ = ['Pipeline', 'Release', 'PipelineError', 'ReleaseError', 'STATE_DIR', 'RELEASE_FILE', 'step_python']

#: Where Leela keeps what it writes into somebody's project.
STATE_DIR = '.leela'
RELEASE_FILE = f'{STATE_DIR}/release.json'
ReleaseError = PipelineError

def step_python(session, root, need=True):
    "The interpreter a step in `root` runs on; `need` refuses a Python project with no pyproject.toml and no venv."
    #: With pyproject.toml the steps are pullup's `uv run`/`uv build`, and uv makes .venv when one needs it.
    root = Path(root)
    if need and python_project(root) and not (root/'pyproject.toml').exists() and (proj := session.missing_venv(root)) is not None:
        raise NoVenv(proj, f'No pyproject.toml and no Python environment in {proj.name}.')
    return session.user_python(root, need=False)

class _Leela:
    "The two things a pipeline of Leela's differs in: where its plan lives, and whose stack it blames."
    def __init__(self, root, python=None, env=None): super().__init__(root, python, env, STATE_DIR)
    def blame(self, checkouts=()): return super().blame(checkouts, FAMILY)

class Pipeline(_Leela, _Pipeline): pass
class Release(_Leela, _Release): pass
