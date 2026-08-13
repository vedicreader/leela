# `connect` and `CAPS` live in `app.py`, which imports fasthtml. Resolved on first access so
# importing this block's domain module never pulls in the web stack.
def __getattr__(name):
    if name in ('CAPS', 'connect'):
        from . import app
        v = globals()[name] = getattr(app, name)
        return v
    raise AttributeError(name)


__all__ = ['connect', 'CAPS']
