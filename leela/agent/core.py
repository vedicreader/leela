"""`leela.agent.core` is `ramabana.core`: the error type, the environment convention, the model tables and routing.

The module object is replaced rather than its names re-exported, so `leela.agent.core`
and `ramabana.core` are the same object and private helpers come across with the rest.
See `leela/agent/__init__.py` for why this package is a seam and not a copy.
"""

import sys

import ramabana.core

# leela's users already have `$LEELA_MODEL` in their shells, and this module is imported
# before anything reads it. `$RAMABANA_MODEL` stays as the fallback, so a variable set for
# the core alone still works -- but inside leela, leela's own name wins.
ramabana.core.use_env_prefix('LEELA_', 'RAMABANA_')

sys.modules[__name__] = ramabana.core
