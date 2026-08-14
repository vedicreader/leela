"""What the server needs from dhrishti, without loading dhrishti into the server.

`dhrishti.core` imports IPython, pandas and numpy at module scope -- right for something whose
job is formatting live values, 660ms and 45MB in a process that only renders its menus and
reads its registry. So the constants and the nine-line registry reader are duplicated here,
and dhrishti stays authoritative: `tests/test_inspectors.py` imports the real thing and fails
if these drift from it. The kernel side is untouched -- `blocks/runtime/kernels.py` still
bootstraps the real dhrishti into every kernel it launches.
"""

from __future__ import annotations

import os
import subprocess

from fastcore.xtras import Path

__all__ = ['PROFILES', 'SORTS', 'reg_dir', 'active', 'alive']

# Mirrors `dhrishti.core.PROFILES`: profile -> what each category does. 'data' is always
# top-level and so is not listed. Pinned by `tests/test_inspectors.py`.
PROFILES = {
    'minimal':  {'type': 'hidden', 'function': 'group', 'module': 'hidden', 'special': 'hidden'},
    'standard': {'type': 'group',  'function': 'group', 'module': 'group',  'special': 'group'},
    'full':     {'type': 'top',    'function': 'top',   'module': 'top',    'special': 'group'},
}

# Mirrors `dhrishti.core.SORTS`: the tree sort orders every frontend shares.
SORTS = ('name', 'recent', 'type', 'size')


def reg_dir():
    "Where live inspectors register themselves; `$DHRISHTI_REG_DIR` overrides it."
    from fastcore.xdg import xdg_config_home
    d = Path(os.environ.get('DHRISHTI_REG_DIR') or xdg_config_home()/'dhrishti'/'reg')
    d.mkdir(parents=True, exist_ok=True)
    return d


def alive(pid):
    "Is `pid` running and not a zombie? `os.kill(pid, 0)` succeeds for a defunct process too."
    try: os.kill(int(pid), 0)
    except ProcessLookupError: return False
    except PermissionError: return True
    except Exception: return False
    try:
        st = subprocess.run(['ps', '-o', 'state=', '-p', str(pid)],
                            capture_output=True, text=True, timeout=2).stdout.strip()
        if st[:1] == 'Z': return False
    # No `ps` (Windows), or it was too slow. `os.kill` already said yes, and a zombie holding a
    # port is the rarer wrong answer than pruning a live inspector.
    except Exception: pass
    return True


def active():
    "Live registry entries, pruning any whose process has gone. The same sweep dhrishti does."
    out = []
    for f in sorted(reg_dir().glob('*.json')):
        try: e = f.read_json()
        except Exception: continue
        if alive(e.get('pid', -1)): out.append(e)
        else:
            try: f.delete()
            except OSError: pass
    return out
