"Probe and install kernel support into a project's environment. kunda's, under Leela's names."

from kunda.pythons import BUNDLE_ONLY, clean_env, strip_bundle  # noqa: F401
from kunda.support import (HOST_PY as LEELA_PY, INSPECTOR, INSPECTOR_TTL,  # noqa: F401
    KERNEL_PACKAGES, as_installed, install_inspector_support, install_kernel_support,
    inspector_support, installable, kernel_support, support_paths, work_dir)

__all__ = ['clean_env', 'strip_bundle', 'BUNDLE_ONLY', 'work_dir', 'support_paths', 'kernel_support',
           'install_kernel_support', 'LEELA_PY', 'INSPECTOR', 'INSPECTOR_TTL', 'KERNEL_PACKAGES',
           'as_installed', 'installable', 'inspector_support', 'install_inspector_support']
