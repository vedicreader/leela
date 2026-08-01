"""leela — notebooks, files and live variables in the terminal and the browser.

leela started inside `dhrishti` and now stands on its own, with no dependency back.
It comes in two halves:

- `leela.inspect` — the engine. It turns a live Python namespace into the node tree
  the frontends render, runs code in it, and serves that over HTTP from inside the
  kernel that owns it. Vendored from dhrishti, where it was authored literately
  under nbdev; leela owns it as plain Python now.
- everything else — the application shell: the workspace, the notebook document,
  the assistant, and the two frontends that draw them.

The whole package is plain Python rather than compiled notebooks. Literate authoring
buys little for a few thousand lines of Textual and FastHTML wiring, and the engine
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
    "Mixin for the dataclasses both frontends serialise: `.dict()` is what routes and JSON payloads call."
    def dict(self): return asdict(self)
