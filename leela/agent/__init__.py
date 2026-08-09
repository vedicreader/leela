"""The coding agent, as part of leela rather than beside it.

This used to live in a separate distribution (`ramabana`) that leela depended on. The
split cost more than it bought: the harness's only consumer was leela, every change had
to be made twice, and the two copies drifted until leela imported module names the
harness no longer had. It is now one package, maintained here, in five modules:

- `core`     -- the error type, the environment convention, the model tables and routing.
- `runtime`  -- native output capture, the context window, compaction, and the backends.
- `tools`    -- `Host` (what an application must provide) and every tool built on it.
- `agent`    -- the turn: the briefing, approvals, the activity feed, `Agent` itself.
- `testing`  -- the doubles: a host with no disk, backends with no model.

Nothing in here imports from `leela` outside this package. That is not modesty about
layering, it is what keeps the harness testable without an IDE: `testing.MemHost` is a
complete host in a dict, and `tests/test_agent.py` runs the whole loop against it.

Everything heavy is imported on first touch. `runtime` reaches for rishi, which loads a
local engine or a cloud client; asking for `leela.agent.Host` must not pay for that.
"""

__all__ = ['Host', 'NullHost', 'Hit', 'Backend', 'Agent', 'Completer', 'Approvals', 'Ask',
           'ModelSpec', 'Routing', 'AgentError', 'agent_err', 'env']

from .core import AgentError, agent_err, env

_lazy = {'Host': ('.tools', 'Host'), 'NullHost': ('.tools', 'NullHost'), 'Hit': ('.tools', 'Hit'),
         'Backend': ('.runtime', 'Backend'), 'Agent': ('.agent', 'Agent'),
         'Completer': ('.agent', 'Completer'), 'Approvals': ('.agent', 'Approvals'),
         'Ask': ('.agent', 'Ask'), 'ModelSpec': ('.core', 'ModelSpec'),
         'Routing': ('.core', 'Routing')}


def __getattr__(name):
    "Import the heavy names on first touch."
    if name in _lazy:
        from importlib import import_module
        mod, attr = _lazy[name]
        return getattr(import_module(mod, __name__), attr)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


def __dir__(): return sorted(list(globals()) + list(_lazy))
