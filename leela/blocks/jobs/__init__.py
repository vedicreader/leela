"Queued work with a visible state, and the cadence for the work that repeats."

__all__ = ['connect', 'CAPS']


# `connect` and `CAPS` live in `app.py`, which imports fasthtml. Resolved on first access so
# importing the domain module does not pull the web stack into a process that never serves.
def __getattr__(name):
    if name in ('CAPS', 'connect'):
        from . import app
        v = globals()[name] = getattr(app, name)
        return v
    raise AttributeError(name)
