"`leela.agent` is `ramabana`, aliased not copied. See docs/integration.md."

from ramabana.core import AgentError, agent_err, env

__all__ = ['Host', 'NullHost', 'Hit', 'Backend', 'Agent', 'Completer', 'Approvals', 'Ask',
           'ModelSpec', 'Routing', 'AgentError', 'agent_err', 'env']
_lazy = dict(Host='tools', NullHost='tools', Hit='tools', Backend='runtime', Agent='agent',
             Completer='agent', Approvals='agent', Ask='agent', ModelSpec='core', Routing='core')

def __getattr__(n):
    if n not in _lazy: raise AttributeError(f'module {__name__!r} has no attribute {n!r}')
    from importlib import import_module
    return getattr(import_module('.'+_lazy[n], __name__), n)

def __dir__(): return sorted(list(globals()) + list(_lazy))
