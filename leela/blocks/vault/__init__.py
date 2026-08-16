"The vault: what is in it, what puts things in it, and the queued work that does the putting."

from .._lazy import lazy_app

__all__ = ['connect', 'CAPS']

__getattr__ = lazy_app(globals())
