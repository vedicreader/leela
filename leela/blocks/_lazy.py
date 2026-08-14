"The lazy `connect`/`CAPS` resolver every block's `__init__` installs, written once."

from importlib import import_module

__all__ = ['lazy_app']

NAMES = ('CAPS', 'connect')


def lazy_app(ns):
    """A module `__getattr__` resolving `connect` and `CAPS` from this block's `app.py`.

    Both live in `app.py`, which imports fasthtml. Resolving them on first access means a
    process that only wants a block's domain module never pulls in the web stack -- and it
    caches into the module's own namespace, so the indirection costs one lookup, once.
    """
    def __getattr__(name):
        if name not in NAMES: raise AttributeError(name)
        v = ns[name] = getattr(import_module(f"{ns['__name__']}.app"), name)
        return v
    return __getattr__
