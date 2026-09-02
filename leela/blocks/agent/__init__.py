"The agent as a leela feature: the adapter between the harness and the IDE."

from .._lazy import lazy_app

__all__ = ['connect', 'CAPS']

__getattr__ = lazy_app(globals())
