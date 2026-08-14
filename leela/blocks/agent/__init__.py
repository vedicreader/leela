"The agent as a leela feature: the adapter between the harness and the IDE."

from ...core.ports import DEFAULT, provider

@provider('runtime', DEFAULT)
def _runtime(spec, **kw):
    from ...agent.runtime import Backend
    return Backend(spec, **kw)
