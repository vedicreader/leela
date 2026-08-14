"""`leela.agent.agent` is `ramabana.agent`: the turn: the briefing, approvals, the activity feed, `Agent` itself.

The module object is replaced rather than its names re-exported, so `leela.agent.agent`
and `ramabana.agent` are the same object and private helpers come across with the rest.
See `leela/agent/__init__.py` for why this package is a seam and not a copy.
"""

import sys

import ramabana.agent

sys.modules[__name__] = ramabana.agent
