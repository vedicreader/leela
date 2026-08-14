"""Leela's features, one folder each.

See `docs/blocks.md` for the contract. Wiring order lives in `leela/app.py`; the first
route to match a path wins, and `tests/routes.txt` pins the resulting URL surface.
"""

# A block that owns a port registers the default implementation for it in its own `__init__`,
# beside the module that satisfies it. `Workspace.__init__` calls `build(...)`, so those
# registrations have to exist by then -- importing the three owners here is what guarantees
# that, whatever route the caller took to reach a workspace.
#
# Cheap on purpose: each factory imports its implementation inside the function body, and a
# block's `__init__` no longer pulls in `app.py`, so this costs three module objects rather
# than the web stack and three subsystems.
from . import agent as _agent_port    # RuntimePort
from . import memory as _memory_port  # MemoryPort
from . import search as _search_port  # SearchPort
