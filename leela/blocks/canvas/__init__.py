"The canvas: a document that runs, the basket a question sends, and the change a boundary claims."

from .._lazy import lazy_app

__all__ = ['connect', 'CAPS']

__getattr__ = lazy_app(globals())
