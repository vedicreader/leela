# `connect` and `CAPS` live in `app.py`, which imports fasthtml. Resolving them lazily keeps
# importing this block's domain module from pulling the web stack into a process that may never
# serve a request.
def __getattr__(name):
    if name in ('CAPS', 'connect'):
        from . import app
        v = globals()[name] = getattr(app, name)
        return v
    raise AttributeError(name)


__all__ = ['connect', 'CAPS']
