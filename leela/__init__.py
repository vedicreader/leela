"leela: notebooks, files and live variables in the terminal and the browser."

__version__ = "0.1.7"

__all__ = ['keys', 'errstr', 'Dictable', 'leela_cfg', 'extras_site', 'extras_bin', 'use_extras',
           'login_path', 'use_login_path', 'TOOL_DIRS', 'use_utf8', 'UTF8_LOCALES']

import sys

from fastcore.xtras import asdict
from fastcore.xdg import xdg_config_home, xdg_data_home

leela_cfg = xdg_config_home()/'leela'

def extras_site():
    "Where an optional backend goes. Not inside the bundle, which is signed and read-only."
    return xdg_data_home()/'leela'/'extras'/f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages'

def extras_bin():
    "Where an extra's console scripts land: `pip install --target X` writes them to `X/bin`."
    return extras_site()/'bin'

def use_extras():
    "Put the extras directory first on `sys.path`, and say whether it was there."
    p = extras_site()
    if str(p) in sys.path: return True
    if not p.is_dir(): return False
    sys.path.insert(0, str(p))
    return True

#: Where user tools live when `launchd` hands an app a PATH with none of them on it.
TOOL_DIRS = ('/opt/homebrew/bin', '/opt/homebrew/sbin', '/usr/local/bin', '~/.local/bin', '~/.cargo/bin')

def login_path(timeout=8):
    "The PATH a person's own terminal has, or None if asking does not work."
    import os
    from .core.envs import shell_env
    out = (shell_env(timeout=timeout) or {}).get('PATH', '').strip()
    return out if out and os.pathsep in out else None

def use_login_path():
    "The PATH a terminal has, for a launch that inherited almost none. `TOOL_DIRS` when asking fails."
    import os
    have = os.environ.get('PATH', '')
    parts = list(dict.fromkeys(filter(None, (login_path() or have).split(os.pathsep))))
    for d in TOOL_DIRS:
        d = os.path.expanduser(d)
        if os.path.isdir(d) and d not in parts: parts.append(d)
    os.environ['PATH'] = os.pathsep.join(parts)
    return os.environ['PATH']

#: Tried in order for `LC_CTYPE`. macOS has the first; the rest are for anywhere else.
UTF8_LOCALES = ('en_US.UTF-8', 'C.UTF-8', 'UTF-8')

def use_utf8():
    "Make the default encoding UTF-8, and say whether it now is. `LC_CTYPE` is what `open` reads."
    import locale
    if 'utf-8' in (locale.getpreferredencoding(False) or '').lower(): return True
    for name in UTF8_LOCALES:
        try: locale.setlocale(locale.LC_CTYPE, name)
        except locale.Error: continue
        if 'utf-8' in (locale.getpreferredencoding(False) or '').lower(): return True
    return False

def errstr(e):
    "How every IDE surface reports a caught exception: `TypeName: message`."
    return f'{type(e).__name__}: {e}'

class Dictable:
    "Mixin for dataclasses serialized by routes and JSON payloads."
    def dict(self): return asdict(self)
