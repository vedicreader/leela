"Build pipelines and releases: what ships, and the steps that ship it. pullup's, under `.leela/`."

from __future__ import annotations

from pullup.env import env_value  # noqa: F401
from pullup.pipeline import Pipeline as _Pipeline, PipelineError, Release as _Release
from pullup.pipeline import resolve_script, uv_argv  # noqa: F401
from pullup.project import (APP_STEPS, CRATE_STEPS, FASTSHIP_STEPS, MATURIN_STEPS,  # noqa: F401
    NBDEV_STEPS, PLAIN_STEPS, Step, app_project, default_steps, fastship_project, maturin_project,
    nbdev_project, release_flow, rust_project)

from ..stack.packages import FAMILY

__all__ = ['Pipeline', 'PipelineError', 'Step', 'env_value', 'resolve_script', 'Release',
           'ReleaseError', 'RELEASE_FILE', 'nbdev_project', 'fastship_project', 'app_project',
           'release_flow', 'default_steps', 'NBDEV_STEPS', 'FASTSHIP_STEPS', 'PLAIN_STEPS',
           'APP_STEPS', 'MATURIN_STEPS', 'CRATE_STEPS', 'rust_project', 'maturin_project']

#: Where Leela keeps what it writes into somebody's project.
STATE_DIR = '.leela'
RELEASE_FILE = f'{STATE_DIR}/release.json'
ReleaseError = PipelineError

class _Leela:
    "The two things a pipeline of Leela's differs in: where its plan lives, and whose stack it blames."
    def __init__(self, root, python=None, env=None): super().__init__(root, python, env, STATE_DIR)
    def blame(self, checkouts=()): return super().blame(checkouts, FAMILY)

class Pipeline(_Leela, _Pipeline): pass
class Release(_Leela, _Release): pass
