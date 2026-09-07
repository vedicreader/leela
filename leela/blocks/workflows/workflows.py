"GitHub Actions, as something you can look at rather than a folder of YAML. pullup's reader."

from pullup.wfbuild import use_spec_dir
from pullup.workflows import WORKFLOW_DIR, WorkflowError, Workflows, levels  # noqa: F401
from pullup.workflows import _gheasy  # noqa: F401  `pipelines.app.fastship_new` asks it for gheasy

__all__ = ['Workflows', 'WorkflowError', 'levels', 'SPEC_DIR']

SPEC_DIR = '.leela/workflows'

#: pullup keeps the spec directory in a module global, which is the only seam it offers. Called
#: here rather than beside the builder, which is imported lazily and so would fire after the first
#: spec had already been written somewhere else. `test_seams.py` asserts it took.
use_spec_dir(SPEC_DIR)
