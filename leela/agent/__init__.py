"`leela.agent` is `ramabana`, aliased not copied: `leela.agent.X` is `ramabana.X`, in one module. See docs/integration.md."

import sys
from importlib import import_module
import ramabana.core
ramabana.core.use_env_prefix('LEELA_', 'RAMABANA_')            # Leela's environment names come first
from ramabana.core import AgentError, agent_err, env

MODULES = ('agent', 'core', 'monitor', 'runtime', 'spec', 'testing', 'tools')
for _n in MODULES: sys.modules[f'{__name__}.{_n}'] = globals()[_n] = import_module(f'ramabana.{_n}')

__all__ = ['Host', 'NullHost', 'Hit', 'Backend', 'Agent', 'Completer', 'Approvals', 'Ask', 'ModelSpec', 'Routing',
           'AgentError', 'agent_err', 'env', *MODULES]
_lazy = dict(Host='tools', NullHost='tools', Hit='tools', Backend='runtime', Agent='agent', Completer='agent',
             Approvals='agent', Ask='agent', ModelSpec='core', Routing='core')

def __getattr__(n):
    if n not in _lazy: raise AttributeError(f'module {__name__!r} has no attribute {n!r}')
    return getattr(globals()[_lazy[n]], n)

def __dir__(): return sorted(list(globals()) + list(_lazy))
