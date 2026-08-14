"What the server needs from dhrishti, without importing it. See `docs/desktop.md`."

from __future__ import annotations

import os
import subprocess

from fastcore.xtras import Path

__all__ = ['PROFILES', 'SORTS', 'reg_dir', 'active', 'alive']

# Mirrors `dhrishti.core.PROFILES`; 'data' is always top-level. Pinned by `tests/test_inspectors.py`.
PROFILES = {
    'minimal':  {'type': 'hidden', 'function': 'group', 'module': 'hidden', 'special': 'hidden'},
    'standard': {'type': 'group',  'function': 'group', 'module': 'group',  'special': 'group'},
    'full':     {'type': 'top',    'function': 'top',   'module': 'top',    'special': 'group'},
}

# Mirrors `dhrishti.core.SORTS`.
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
    except Exception: pass   # no `ps`, or too slow; `os.kill` already said yes
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
