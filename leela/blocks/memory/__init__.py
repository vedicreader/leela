"Durable prose: pages, research briefs, agent notes and saved state, over litesearch."

from .._lazy import lazy_app
from ...core.providers import DEFAULT, provider

__all__ = ['connect', 'CAPS']

__getattr__ = lazy_app(globals())

@provider('memory', DEFAULT)
def _memory(kosha=None, path=None, **kw):
    from .memory import Memory
    return Memory(kosha=kosha, path=path, **kw)
