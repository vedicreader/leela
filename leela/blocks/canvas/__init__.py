"The canvas document: a goal, its plan, its research, its code, its questions, and its changes."

from .._lazy import lazy_app

__all__ = ['connect', 'CAPS']

__getattr__ = lazy_app(globals())
