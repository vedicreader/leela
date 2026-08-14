"""The coding agent, which is now `ramabana` rather than a copy of it kept here.

This package was a fork. The harness lived in `ramabana`, leela vendored it, and for a
while that was cheaper than the dependency -- until the two copies drifted far enough that
each had fixes the other did not. leela's copy had grown `run_shell`, exact-text editing,
`grep`, the `ERROR:` failure convention and `AGENTS.md`; ramabana's had grown a vault, a
shopping cart, a real filesystem `Host`, an MCP server and a per-turn usage ledger.
Neither was "the" harness, which is where a fork always ends up.

They are merged, `ramabana` is the agent core, and this package is the seam: the same five
module paths leela has always imported, each one an alias for the module that now holds
the code.

- `leela.agent.core`     -> `ramabana.core`     -- the error type, the environment, model routing.
- `leela.agent.runtime`  -> `ramabana.runtime`  -- native capture, the context window, the backends.
- `leela.agent.tools`    -> `ramabana.tools`    -- `Host` and every tool built on it.
- `leela.agent.agent`    -> `ramabana.agent`    -- the turn: briefing, approvals, activity, `Agent`.
- `leela.agent.testing`  -> `ramabana.testing`  -- the doubles: a host with no disk, no model.

Each of those files replaces its own module object rather than re-exporting a list of
names. leela reaches for private helpers -- `tools._cmds`, `tools._edits`,
`tools._apply_edits` in `app.py` -- and a hand-written export list would have to be kept in
step with them, which is the drift this merge exists to end.

Nothing here imports from `leela`, and nothing in `ramabana` does either. That is not
layering pedantry: `testing.MemHost` is a complete host in a dict, and it is what lets the
whole loop be tested without starting an IDE.

Everything heavy is still imported on first touch. `runtime` reaches for rishi, which
loads a local engine or a cloud client; asking for `leela.agent.Host` must not pay for that.
"""

__all__ = ['Host', 'NullHost', 'Hit', 'Backend', 'Agent', 'Completer', 'Approvals', 'Ask',
           'ModelSpec', 'Routing', 'AgentError', 'agent_err', 'env']

from ramabana.core import AgentError, agent_err, env

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
