"Durable prose: pages, research briefs, agent notes and saved state, over litesearch."

from ...core.providers import DEFAULT, provider

__all__ = ['connect', 'CAPS']


# Resolved on first access, so importing this block's domain module does not pull in fasthtml.
def __getattr__(name):
    if name in ('CAPS', 'connect'):
        from . import app
        v = globals()[name] = getattr(app, name)
        return v
    raise AttributeError(name)


# This block owns `MemoryPort`, so it registers what satisfies it. `vishalakshi.Vault`
# registers the same way -- see `docs/integration.md`.
@provider('memory', DEFAULT)
def _memory(kosha=None, path=None, **kw):
    from .memory import Memory
    return Memory(kosha=kosha, path=path, **kw)
