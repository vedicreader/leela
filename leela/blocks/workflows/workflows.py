"GitHub Actions, as something you can look at rather than a folder of YAML. pullup's reader."

from pullup.wfbuild import use_spec_dir
from pullup.workflows import WORKFLOW_DIR, WorkflowError, Workflows, levels  # noqa: F401
from pullup.workflows import _gheasy  # noqa: F401  `pipelines.app.fastship_new` asks it for gheasy

__all__ = ['Workflows', 'WorkflowError', 'levels', 'SPEC_DIR']

SPEC_DIR = '.leela/workflows'

# Beside `Workflows` and not beside the builder: `Workflows` writes and reads specs itself, and the
# builder is imported lazily, so configuring it there left every spec written before the panel
# opened in pullup's own visible `workflows/` folder.
use_spec_dir(SPEC_DIR)
