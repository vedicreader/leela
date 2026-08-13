"""Code search: literal, structural and semantic, over Kosha plus ripgrep."""

from ...core.providers import DEFAULT, provider

__all__ = ['connect', 'CAPS']


# `connect` and `CAPS` live in `app.py`, which imports fasthtml. Resolved on first access so
# importing this block's domain module never pulls in the web stack.
def __getattr__(name):
    if name in ('CAPS', 'connect'):
        from . import app
        v = globals()[name] = getattr(app, name)
        return v
    raise AttributeError(name)


# This block owns `SearchPort`, so it registers what satisfies it. The import sits inside the
# factory, so naming a provider costs nothing until the workspace builds one.
@provider('search', DEFAULT)
def _search(fs, **kw):
    from .search import Search
    return Search(fs, **kw)
