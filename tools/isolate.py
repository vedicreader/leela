"""Point every store that Leela and its packages write at a temporary folder.

Call `isolate()` before `import leela`: `leela_cfg` and some package paths are bound at import.

    from tools.isolate import isolate
    isolate()
"""
import os, tempfile
from pathlib import Path

_home = Path.home()
#: The person's real stores. No test and no tool writes under them.
REAL_STORES = [_home/'.config'/'leela', _home/'.local'/'share'/'leela', _home/'.cache'/'leela', _home/'.vishalakshi',
               _home/'.config'/'ramabana', _home/'.config'/'abhyasa']

def isolated_env(base):
    "The variables that move each store under `base`."
    b = Path(base)
    return dict(XDG_CONFIG_HOME=b, XDG_DATA_HOME=b/'data', XDG_CACHE_HOME=b/'cache', VISHALAKSHI_VAULT=b/'vault'/'vault.db',
                LEELA_SEARCH_VAULT=b/'vault'/'search.db', ABHYASA_CONFIG=b/'abhyasa', RAMABANA_CONFIG=b/'ramabana'/'config.toml',
                LEELA_MEMORY_OFFLINE='1')

def isolate(base=None):
    "Set the stores' variables under `base` (a new temporary folder if None), move ramabana's probes there, and return `base`."
    b = Path(base or tempfile.mkdtemp(prefix='leela-iso-'))
    os.environ.update({k: str(v) for k, v in isolated_env(b).items()})
    isolate_probes(b)
    return b

def isolate_probes(base):
    "ramabana keeps its probes in a fixed `~/.config/ramabana/probes`, and no variable moves it."
    import ramabana.core as rc
    rc.PROBE_DIR = Path(base)/'ramabana'/'probes'
