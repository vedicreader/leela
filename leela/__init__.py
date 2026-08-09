"""leela — notebooks, files and live variables in the terminal and the browser.

leela started inside `dhrishti` and comes in two halves:

- `dhrishti` — the engine, and now a dependency again. It turns a live Python namespace
  into the node tree the frontends render, runs code in it, and serves that as a JSON API
  from inside the kernel that owns it. leela vendored it as `leela.inspect` for a while and
  evolved it; that work went back upstream, and dhrishti is a JSON API with no frontend of
  its own, which is exactly what leela wants from it.
- everything else, here — the application shell: the workspace, the notebook document,
  the assistant, and the two frontends that draw them.

The whole package is plain Python rather than compiled notebooks. Literate authoring
buys little for a few thousand lines of FastHTML and browser wiring, and the engine
is easier to keep honest under the pytest suite in `tests/` than under nbdev.
"""

__version__ = "0.0.1"

__all__ = ['keys', 'errstr', 'Dictable', 'leela_cfg']

from fastcore.xtras import asdict
from fastcore.xdg import xdg_config_home

# leela's own config dir, deliberately *not* dhrishti's. The workspace, captured
# screens and everything else the IDE persists belong to the IDE; sharing a
# directory with the library would mean uninstalling one loses the other's state.
leela_cfg = xdg_config_home()/'leela'


def errstr(e):
    "How every IDE surface reports a caught exception: `TypeName: message`."
    return f'{type(e).__name__}: {e}'


class Dictable:
    "Mixin for dataclasses serialized by routes and JSON payloads."
    def dict(self): return asdict(self)
