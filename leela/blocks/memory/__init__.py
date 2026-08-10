"""Durable prose: pages, research briefs, agent notes and saved state, over litesearch."""

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


# This block owns `MemoryPort`, so it registers what satisfies it, beside the module that
# does. `vishalakshi.Vault` registers the same way, which is what lets the two be compared on
# equal terms -- see `docs/integration.md`.
@provider('memory', DEFAULT)
def _memory(kosha=None, path=None, **kw):
    from .memory import Memory
    return Memory(kosha=kosha, path=path, **kw)
