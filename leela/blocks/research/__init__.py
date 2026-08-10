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


__all__ = ['connect', 'CAPS']
