"Web pages as tabs, rendered by the persistent CDP Chrome."

from .._lazy import lazy_app

__all__ = ['connect', 'CAPS']

__getattr__ = lazy_app(globals())
