"Source text of the browser assets and the web layer, as single strings."

from functools import cache
from pathlib import Path

__all__ = ['ROOT', 'JS', 'CSS', 'EDITOR', 'TERM', 'SERVER', 'AGENT', 'read', 'tree_text',
           'cm_exports']

ROOT = Path(__file__).resolve().parents[1]

def tree_text(rel, glob):
    "Every `glob` file under `rel`, sorted by path, joined with newlines."
    d = ROOT/rel
    if not d.is_dir(): return ''
    return '\n'.join(p.read_text() for p in sorted(d.rglob(glob)))

@cache
def read(rel):
    "One file's text, cached. Empty string when it does not exist."
    p = ROOT/rel
    return p.read_text() if p.is_file() else ''

@cache
def _static(glob): return tree_text('leela/static', glob) + '\n' + tree_text('leela/vendor', glob)

@cache
def _agent():
    "The harness's source, which is `ramabana` and no longer a copy of it in this tree."
    import ramabana
    d = Path(ramabana.__file__).parent
    return '\n'.join(p.read_text() for p in sorted(d.rglob('*.py')))

@cache
def _server():
    return tree_text('leela', '*.py')

@cache
def _authored_js(): return tree_text('leela/static', '*.js')

_CORPORA = {'JS':     _authored_js,
            'CSS':    lambda: _static('*.css'),
            'EDITOR': lambda: read('frontend/editor.js'),
            'TERM':   lambda: read('frontend/term.js'),
            'SERVER': _server,
            'AGENT':  _agent}

def __getattr__(name):
    if name not in _CORPORA: raise AttributeError(name)
    v = globals()[name] = _CORPORA[name]()
    return v

@cache
def cm_exports():
    """The names `leela/vendor/lee-cm6.js` exports, read from the map itself.

    The call that builds the map is named by the minifier, so anchoring on it broke on the next
    rebuild of any part of `frontend/editor.js` and read as a dropped export.
    """
    import re
    b = read('leela/vendor/lee-cm6.js')
    i = b.index('undo:()=>')
    return set(re.findall(r'(\w+)\s*:\s*\(\)\s*=>', b[b.rfind('{', 0, i):b.index('}', i)]))
