"""Choosing which implementation satisfies a port.

`ports.py` says what leela needs. This says how an alternative gets selected, and it exists
so that trying `vishalakshi` or `ramabana` is a configuration change rather than an edit.

    LEELA_MEMORY=vishalakshi leela .

Three properties matter more than the mechanism:

**Selection is late.** A provider is a zero-argument factory, resolved when the workspace
builds the subsystem, not at import. Naming a provider therefore costs nothing until it is
used, and a provider whose package is not installed fails at the moment you asked for it,
naming what to install.

**Failure is loud.** An unknown or broken provider raises. Silently falling back to the
built-in would make an A/B comparison meaningless -- you would not know which one answered,
which is precisely the question being asked.

**The built-in is a provider too.** `leela` is registered like any other, so there is no
privileged path that only the default takes and no untested branch for the alternates.

Registration happens at import of the block that owns the port, or from a plugin calling
`register`. Nothing here imports vishalakshi or ramabana; the entries below are lazy, so
they resolve only if selected.
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
    """Make `name` available for `port`. `factory` takes whatever the port's builder passes.

    Re-registering the same name replaces it, which is what lets a test install a fake
    without unregistering first.
    """
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
    """Construct the implementation selected for `port`.

    Raises rather than falling back. A workspace that quietly ran on the built-in after
    `LEELA_MEMORY=vishalakshi` failed to load would produce a comparison that means nothing.
    """
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


# -- the built-ins -----------------------------------------------------------
# Registered like any other provider, with the import inside the factory so that selecting
# a different one does not pay for these, and so `leela.core` stays importable without the
# heavier subsystems being constructed.

@provider('search', DEFAULT)
def _leela_search(fs, **kw):
    from ..blocks.search.search import Search
    return Search(fs, **kw)


@provider('memory', DEFAULT)
def _leela_memory(kosha=None, path=None, **kw):
    from ..blocks.memory.memory import Memory
    return Memory(kosha=kosha, path=path, **kw)


@provider('runtime', DEFAULT)
def _leela_runtime(spec, **kw):
    from ..agent.runtime import Backend
    return Backend(spec, **kw)
