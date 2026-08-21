"The agent as a leela feature: the adapter between the harness and the IDE."

from .._lazy import lazy_app
from ...core.ports import DEFAULT, provider

__all__ = ['connect', 'CAPS']

__getattr__ = lazy_app(globals())

@provider('runtime', DEFAULT)
def _runtime(spec, **kw):
    from ...agent.runtime import Backend
    return Backend(spec, **kw)
