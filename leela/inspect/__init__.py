"""The inspection engine leela runs inside each kernel.

This is the half of leela that does not draw anything: it turns a live Python namespace
into the grouped, expandable node tree the frontends render, runs code in that namespace,
and serves both over HTTP from inside the kernel that owns them.

It was vendored from `dhrishti`, where it was authored literately under nbdev. leela owns
it as plain Python now — the same choice the rest of leela already makes. What came across
is only what leela uses: the inspection core, the execution bridge, the agent overlay, and
the JSON API. dhrishti's own terminal frontend and its htmx inspector UI stayed behind.
"""

from .core import *
from .runtime import *
from .agent import *


def __getattr__(name):
    """`serve` and `watch` on demand, without importing the server.

    `leela.inspect.server` pulls in fasthtml and uvicorn, which is a lot to load into
    someone's kernel just to look at a namespace. But `import leela.inspect as li;
    li.serve(name='api')` is the line a person types to make their *own* process show up in
    the IDE's env picker, so it has to work as written.
    """
    if name in ('serve', 'watch', 'active', 'register'):
        from importlib import import_module
        return getattr(import_module('.server', __name__), name)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
