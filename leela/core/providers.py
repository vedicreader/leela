"""Choosing which implementation satisfies a port, e.g. `LEELA_MEMORY=vishalakshi leela .`

A provider is a zero-argument factory resolved when the workspace builds the subsystem, so
naming one costs nothing until it is used. An unknown or broken provider raises rather than
falling back to the built-in, which is registered like any other provider.
"""

from __future__ import annotations

import os

__all__ = ['register', 'provider', 'build', 'providers_for', 'selected', 'ProviderError']

# port name -> provider name -> zero-argument factory
_REGISTRY: dict[str, dict[str, callable]] = {}

# port name -> the environment variable that selects it
ENV = {'memory': 'LEELA_MEMORY', 'search': 'LEELA_SEARCH', 'runtime': 'LEELA_RUNTIME'}

DEFAULT = 'leela'


class ProviderError(RuntimeError):
    "An implementation was asked for by name and could not be produced."


def register(port, name, factory):
    "Make `name` available for `port`; re-registering the same name replaces it."
    _REGISTRY.setdefault(port, {})[name] = factory
    return factory


def provider(port, name):
    "Decorator form of `register`."
    def deco(fn): return register(port, name, fn)
    return deco


def providers_for(port):
    "Every registered provider name for `port`, defaults first."
    names = sorted(_REGISTRY.get(port, {}))
    return ([DEFAULT] if DEFAULT in names else []) + [n for n in names if n != DEFAULT]


def selected(port, override=None):
    "Which provider `port` should use: explicit override, then environment, then the default."
    if override: return override
    return os.environ.get(ENV.get(port, ''), '') or DEFAULT


def build(port, *a, override=None, **kw):
    "Construct the implementation selected for `port`, raising rather than falling back."
    name = selected(port, override)
    factories = _REGISTRY.get(port, {})
    if name not in factories:
        known = ', '.join(providers_for(port)) or 'none registered'
        raise ProviderError(f'unknown {port} provider {name!r}; available: {known}')
    try:
        return factories[name](*a, **kw)
    except ImportError as e:
        raise ProviderError(
            f'{port} provider {name!r} is selected but its package is not installed: {e}') from e
    except Exception as e:
        raise ProviderError(f'{port} provider {name!r} failed to start: {type(e).__name__}: {e}') from e


# No built-in registrations here: `core` names no implementation. Each block registers the
# default for the port it owns, and `leela/blocks/__init__.py` imports `search`, `memory` and
# `agent` so those registrations exist before `Workspace.__init__` calls `build`.
