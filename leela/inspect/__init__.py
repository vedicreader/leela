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
