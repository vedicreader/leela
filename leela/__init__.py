"""leela — notebooks, files and live variables in the terminal and the browser.

leela is the IDE that grew up inside `dhrishti` and now lives in its own repository.
It stays a *frontend*: the inspection core it renders — `dhrishti.core`,
`dhrishti.runtime`, `dhrishti.agent`, `dhrishti.serving` — remains nbdev-authored
over in dhrishti, and leela depends on it like any other library.

Unlike dhrishti, this package is plain Python rather than compiled notebooks: it is
application shell, and literate notebook authoring buys little for a few thousand
lines of Textual and FastHTML wiring. It has a pytest suite under `tests/` instead.
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
