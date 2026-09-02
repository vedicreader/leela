"The six gheasy helpers Leela imports, public in 0.0.10 and underscored before it."

from __future__ import annotations

import gheasy.core as _core
import gheasy.repo as _repo
import gheasy.workflow as _workflow

__all__ = ['invalidate', 'plural', 'unborn', 'gh_api', 'gh_token', 'yaml_instance']

def _opened(mod, name, was=None):
    "The public name, or the one gheasy has not opened yet."
    for n in (name, was or f'_{name}'):
        if (got := getattr(mod, n, None)) is not None: return got
    raise ImportError(f'{mod.__name__} has neither {name} nor {was or "_" + name}')

invalidate = _opened(_repo, 'invalidate')
plural = _opened(_repo, 'plural')
unborn = _opened(_repo, 'unborn')
gh_api = _opened(_core, 'gh_api')
gh_token = _opened(_core, 'gh_token', '_resolve_gh_token')
yaml_instance = _opened(_workflow, 'yaml_instance')
