"""`leela.agent.runtime` is `ramabana.runtime`: native output capture, the context window, compaction, and the backends.

The module object is replaced rather than its names re-exported, so `leela.agent.runtime`
and `ramabana.runtime` are the same object and private helpers come across with the rest.
See `leela/agent/__init__.py` for why this package is a seam and not a copy.
"""

import sys

import ramabana.runtime

sys.modules[__name__] = ramabana.runtime
