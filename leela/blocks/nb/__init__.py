"The notebook: the document, its cells, and the routes that run and save them."

from .._lazy import lazy_app

__all__ = ['connect', 'CAPS']

__getattr__ = lazy_app(globals())
