"Code search: literal, structural and semantic, over Kosha plus ripgrep."

from .._lazy import lazy_app

__all__ = ['connect', 'CAPS']

__getattr__ = lazy_app(globals())
