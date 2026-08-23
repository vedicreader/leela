"leela: notebooks, files and live variables in the terminal and the browser."

__version__ = "0.1.0"

__all__ = ['keys', 'errstr', 'Dictable', 'leela_cfg', 'extras_site', 'use_extras',
           'login_path', 'use_login_path', 'TOOL_DIRS']

import sys

from fastcore.xtras import asdict
from fastcore.xdg import xdg_config_home, xdg_data_home

leela_cfg = xdg_config_home()/'leela'

def extras_site():
    "Where an optional backend goes. Not inside the bundle, which is signed and read-only."
    return xdg_data_home()/'leela'/'extras'/f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages'

def use_extras():
    """Put the extras directory first on `sys.path`, and say whether it was there.

    First, so a backend installed there later beats a stale copy inside the bundle."""
    p = extras_site()
    if str(p) in sys.path: return True
    if not p.is_dir(): return False
    sys.path.insert(0, str(p))
    return True

#: Where user tools live when `launchd` hands an app a PATH with none of them on it.
TOOL_DIRS = ('/opt/homebrew/bin', '/opt/homebrew/sbin', '/usr/local/bin', '~/.local/bin', '~/.cargo/bin')

def login_path(timeout=3):
    "The PATH an interactive shell would have, or None if asking does not work."
    import os, subprocess
    sh = os.environ.get('SHELL')
    if not sh: return None
    try:
        p = subprocess.run([sh, '-l', '-c', 'printf %s "$PATH"'], capture_output=True, text=True,
                           timeout=timeout)
    except Exception: return None
    return out if p.returncode == 0 and (out := p.stdout.strip()) and os.pathsep in out else None

def use_login_path():
    """Give a windowed launch the PATH a terminal has, and return it.

    Finder and the Dock start an app with almost nothing on PATH, so `git`, `claude`, `ollama` and
    `uv` all go missing and Leela reports them as not installed. The login shell is asked first
    because a developer's tools are wherever they put them; `TOOL_DIRS` is the fallback.
    """
    import os
    have = os.environ.get('PATH', '')
    parts = list(dict.fromkeys(filter(None, (login_path() or have).split(os.pathsep))))
    for d in TOOL_DIRS:
        d = os.path.expanduser(d)
        if os.path.isdir(d) and d not in parts: parts.append(d)
    os.environ['PATH'] = os.pathsep.join(parts)
    return os.environ['PATH']

def errstr(e):
    "How every IDE surface reports a caught exception: `TypeName: message`."
    return f'{type(e).__name__}: {e}'

class Dictable:
    "Mixin for dataclasses serialized by routes and JSON payloads."
    def dict(self): return asdict(self)
