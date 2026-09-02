"Building a workflow by choosing, not by typing YAML. pullup's builder, in Leela's own directory."

from pullup.wfbuild import PRESETS, TRIGGERS, compose, deploy_job, fastship_job  # noqa: F401
from pullup.wfbuild import load_spec as _load_spec, nbdev_job, preset_rows
from pullup.wfbuild import save_spec as _save_spec, spec_path as _spec_path

__all__ = ['PRESETS', 'TRIGGERS', 'compose', 'deploy_job', 'nbdev_job', 'fastship_job', 'spec_path',
           'load_spec', 'save_spec', 'preset_rows']

SPEC_DIR = '.leela/workflows'

def spec_path(root, file): return _spec_path(root, file, SPEC_DIR)

def load_spec(root, file):
    "The spec a workflow was built from, or None when it was written some other way."
    return _load_spec(root, file, SPEC_DIR)

def save_spec(root, file, spec): return _save_spec(root, file, spec, SPEC_DIR)
