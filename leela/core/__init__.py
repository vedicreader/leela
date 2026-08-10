"""What every block is allowed to import.

The rule that keeps blocks independent is a one-way dependency: blocks import `leela.core`,
`leela.core` imports no block, and blocks do not import each other. Anything two blocks
both need belongs here; anything only one needs belongs in that block.

`leela.core` deliberately stays thin. lego's core carries config, logging, caching, the
scheduler and the base UI because a lego app's blocks are otherwise unrelated features that
share nothing else. Leela's blocks all sit on one live kernel and one document model, so
their common ground is already `Workspace`, `Notebook` and `KernelPool` -- core's job is
not to re-export those, it is to define *how a block reaches them* (`Ctx`) and *what may be
swapped out underneath* (`ports`).
"""

from .block import Block, block_caps, connect_all
from .ctx import APP, CAPABILITIES, EAGER, LAZY, Ctx
from .ports import MemoryPort, RuntimePort, SearchPort
from .providers import ProviderError, build, provider, providers_for, register, selected
from .session import DebugState, DocStore, RunState


# `conformance` used to be re-exported from here. It now lives at `leela/conformance.py`,
# because checking a provider means building one, and building one needs `fs.Sandbox` and
# `agent.core.resolve` -- so the diagnostic has to name implementations, which is exactly what
# core must not do. Run it as `python -m leela.conformance`, or import `leela.conformance`.

__all__ = ['Ctx', 'CAPABILITIES', 'EAGER', 'LAZY', 'APP',
           'Block', 'connect_all', 'block_caps',
           'DocStore', 'DebugState', 'RunState',
           'MemoryPort', 'SearchPort', 'RuntimePort',
           'register', 'provider', 'build', 'providers_for', 'selected', 'ProviderError']
