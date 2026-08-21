"The debugger: debugpy availability, one debug session over a kernel, and the direct DAP routes."

from .._lazy import lazy_app

__all__ = ['connect', 'CAPS']

__getattr__ = lazy_app(globals())
