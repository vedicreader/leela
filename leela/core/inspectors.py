"""What the server needs from dhrishti, without loading dhrishti into the server.

dhrishti's place is *inside a kernel*. `dhrishti.core` imports IPython, pandas and numpy at
module scope, which is right for something whose job is formatting live values, and which
costs 660ms and 45MB in a process that never formats one. Leela's server does two things with
dhrishti: it renders the profile and sort menus, and it reads the directory of JSON files that
in-kernel inspectors register themselves in to find out which are alive. Neither needs a
DataFrame.

So the constants and the registry reader are duplicated here, deliberately and in full view.
dhrishti stays authoritative: `tests/test_inspectors.py` imports the real thing and fails if
these drift from it, which is a better failure than a Leela that quietly disagrees with the
inspectors it is talking to. The registry is a file format shared between processes, not an
API -- Leela is one of its readers, and reading it is nine lines.

The kernel side is untouched. `blocks/runtime/kernels.py` still bootstraps the real dhrishti
into every kernel it launches, which is where the dependency belongs and why it stays in
`pyproject.toml`.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from .. import leela_cfg  # noqa: F401  (imported for its xdg side of the config contract)

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
    # No `ps` (Windows), or it was too slow to answer. `os.kill` already said yes, and a
    # zombie holding a port is the rarer wrong answer than pruning a live inspector.
    except Exception: pass
    return True


def active():
    "Live registry entries, pruning any whose process has gone. The same sweep dhrishti does."
    out = []
    for f in sorted(reg_dir().glob('*.json')):
        try: e = json.loads(f.read_text())
        except Exception: continue
        if alive(e.get('pid', -1)): out.append(e)
        else:
            try: f.unlink()
            except OSError: pass
    return out
