"leela — notebooks, files and live variables in the terminal and the browser."

__version__ = "0.1.0"

__all__ = ['keys', 'errstr', 'Dictable', 'leela_cfg', 'extras_site', 'use_extras']

import sys

from fastcore.xtras import asdict
from fastcore.xdg import xdg_config_home, xdg_data_home

leela_cfg = xdg_config_home()/'leela'

def extras_site():
    "Where an optional backend is installed. Never inside the bundle: that is signed and read-only."
    return xdg_data_home()/'leela'/'extras'/f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages'

def use_extras():
    """Put the extras directory ahead of the frozen library, and say whether it was there.

    A frozen app cannot install into itself, so `leela[local]` lands beside it and is imported from
    here. First on `sys.path` so a backend installed later wins over anything stale the bundle
    carries. A normal install needs none of this: its own environment is what gets installed into.
    """
    p = extras_site()
    if str(p) in sys.path: return True
    if not p.is_dir(): return False
    sys.path.insert(0, str(p))
    return True

def errstr(e):
    "How every IDE surface reports a caught exception: `TypeName: message`."
    return f'{type(e).__name__}: {e}'

class Dictable:
    "Mixin for dataclasses serialized by routes and JSON payloads."
    def dict(self): return asdict(self)
