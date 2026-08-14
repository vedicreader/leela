"""`leela.agent.tools` is `ramabana.tools`: `Host` (what an application must provide) and every tool built on it.

The module object is replaced rather than its names re-exported, so `leela.agent.tools`
and `ramabana.tools` are the same object and private helpers come across with the rest.
See `leela/agent/__init__.py` for why this package is a seam and not a copy.
"""

import sys

import ramabana.tools

sys.modules[__name__] = ramabana.tools
