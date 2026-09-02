"Getting a web app onto a VM: a Dockerfile, a tunnel, a server, and the keys CI needs. pullup's."

from pullup.deploy import DEPLOY_KEYS, DEPLOY_STEPS, deploy_template, setup_template  # noqa: F401
from pullup.deploy import Deploy as _Deploy, use_generator

from .pipelines import STATE_DIR, PipelineError, _Leela

__all__ = ['Deploy', 'DeployError', 'DEPLOY_FILE', 'DEPLOY_KEYS', 'deploy_template',
           'setup_template']

DEPLOY_FILE = f'{STATE_DIR}/deploy.json'
DeployError = PipelineError

# A `setup.py` or `deploy.py` written into somebody's repository says Leela wrote it.
use_generator('Leela')

class Deploy(_Leela, _Deploy): pass
