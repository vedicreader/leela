"Durable prose: pages, research briefs, agent notes and saved state, over litesearch."

from .._lazy import lazy_app

__all__ = ['connect', 'CAPS']

__getattr__ = lazy_app(globals())
