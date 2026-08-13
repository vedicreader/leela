# Lazy: `app.py` imports fasthtml, and importing this block's domain must not pull in the web stack.
def __getattr__(name):
    if name in ('CAPS', 'connect'):
        from . import app
        v = globals()[name] = getattr(app, name)
        return v
    raise AttributeError(name)


__all__ = ['connect', 'CAPS']
