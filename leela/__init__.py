"leela — notebooks, files and live variables in the terminal and the browser."

__version__ = "0.0.1"

__all__ = ['keys', 'errstr', 'Dictable', 'leela_cfg']

from fastcore.xtras import asdict
from fastcore.xdg import xdg_config_home

leela_cfg = xdg_config_home()/'leela'

def errstr(e):
    "How every IDE surface reports a caught exception: `TypeName: message`."
    return f'{type(e).__name__}: {e}'

class Dictable:
    "Mixin for dataclasses serialized by routes and JSON payloads."
    def dict(self): return asdict(self)
