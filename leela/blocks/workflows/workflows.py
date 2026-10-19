"GitHub Actions, as something you can look at rather than a folder of YAML. pullup's reader."

from pullup.wfbuild import use_spec_dir
from pullup.workflows import WORKFLOW_DIR, WorkflowError, Workflows, levels  # noqa: F401
from pullup.workflows import gheasy_core  # noqa: F401  `pipelines.app.fastship_new` asks it for gheasy

__all__ = ['Workflows', 'WorkflowError', 'levels', 'SPEC_DIR']

SPEC_DIR = '.leela/workflows'

#: Set here, not beside the lazily-imported builder, which would fire after the first spec was already written.
use_spec_dir(SPEC_DIR)
