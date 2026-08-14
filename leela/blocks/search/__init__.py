"Code search: literal, structural and semantic, over Kosha plus ripgrep."

from .._lazy import lazy_app
from ...core.providers import DEFAULT, provider

__all__ = ['connect', 'CAPS']

__getattr__ = lazy_app(globals())

@provider('search', DEFAULT)
def _search(fs, **kw):
    from .search import Search
    return Search(fs, **kw)
