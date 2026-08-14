"Queued work with a visible state, and the cadence for the work that repeats."

from .._lazy import lazy_app

__all__ = ['connect', 'CAPS']

__getattr__ = lazy_app(globals())
