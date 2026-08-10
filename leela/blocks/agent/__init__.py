"""The agent as a leela feature: the adapter between the harness and the IDE.

`ai.py` is the adapter -- it gives `leela.agent`'s `Host` protocol a real workspace to act
on -- and `models.py` is the user's saved model list. The harness itself stays at
`leela/agent/`, a package that imports nothing from leela so the whole agent loop can be
tested against a dict (`tests/test_agent.py::test_agent_package_does_not_import_leela`).

That boundary is where `RuntimePort` substitutes: porting the harness to ramabana replaces
`leela/agent/` wholesale and leaves this block as the wiring.

Domain only for now. The 45 agent routes are still closures in `leela/app.py` -- the largest
group left -- and land here as `app.py` when they move.
"""

from ...core.providers import DEFAULT, provider


# This block owns `RuntimePort`, so it registers what satisfies it. The port covers mechanism
# only -- history, streaming, tools, cancellation -- because compaction, token accounting and
# model resolution are leela's policy about how to *use* a runtime, and keeping them out is
# what lets two runtimes be compared on equal terms. `ramabana` registers the same way.
@provider('runtime', DEFAULT)
def _runtime(spec, **kw):
    from ...agent.runtime import Backend
    return Backend(spec, **kw)
