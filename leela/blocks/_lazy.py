"The lazy `connect`/`CAPS` resolver every block's `__init__` installs, written once."

from importlib import import_module

__all__ = ['lazy_app']

NAMES = ('CAPS', 'connect')

def lazy_app(ns):
    "A module `__getattr__` resolving `connect` and `CAPS` from this block's `app.py`."
    def __getattr__(name):
        if name not in NAMES: raise AttributeError(name)
        v = ns[name] = getattr(import_module(f"{ns['__name__']}.app"), name)
        return v
    return __getattr__
