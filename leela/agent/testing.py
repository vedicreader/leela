"""`leela.agent.testing` is `ramabana.testing`: the doubles: a host with no disk, backends with no model.

The module object is replaced rather than its names re-exported, so `leela.agent.testing`
and `ramabana.testing` are the same object and private helpers come across with the rest.
See `leela/agent/__init__.py` for why this package is a seam and not a copy.
"""

import sys

import ramabana.testing

sys.modules[__name__] = ramabana.testing
