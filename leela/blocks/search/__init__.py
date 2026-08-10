"""Code search: literal, structural and semantic, over Kosha plus ripgrep."""

from ...core.providers import DEFAULT, provider

__all__ = ['connect', 'CAPS']


# `connect` and `CAPS` live in `app.py`, which imports fasthtml. Resolving them on first
# access is what keeps importing this block's domain module -- which `Workspace` does for the
# services it composes -- from pulling the whole web stack into a process that may never serve
# a request.
def __getattr__(name):
    if name in ('CAPS', 'connect'):
        from . import app
        v = globals()[name] = getattr(app, name)
        return v
    raise AttributeError(name)


# This block owns `SearchPort`, so it registers what satisfies it, beside the module that
# does. The import sits inside the factory, so naming a provider costs nothing until the
# workspace actually builds one.
@provider('search', DEFAULT)
def _search(fs, **kw):
    from .search import Search
    return Search(fs, **kw)
