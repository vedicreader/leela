"""The agent as a leela feature: the adapter between the harness and the IDE.

`ai.py` gives ramabana's `Host` protocol a real workspace to act on; `models.py` is the user's
saved model list. The harness stays at `leela/agent/`, a package that imports nothing from leela
(`tests/test_agent.py::test_agent_package_does_not_import_leela`). Domain only for now: the agent
routes are still closures in `leela/app.py`.
"""

from ...core.providers import DEFAULT, provider


# This block owns `RuntimePort`, so it registers what satisfies it. The port covers mechanism
# only; compaction, token accounting and model resolution are leela's policy about how to *use* a
# runtime, and keeping them out is what lets two runtimes be compared on equal terms.
@provider('runtime', DEFAULT)
def _runtime(spec, **kw):
    from ...agent.runtime import Backend
    return Backend(spec, **kw)
