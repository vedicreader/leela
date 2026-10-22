"Source text of the browser assets and the web layer, as single strings."

from functools import cache
from pathlib import Path

__all__ = ['ROOT', 'JS', 'CSS', 'EDITOR', 'TERM', 'SERVER', 'AGENT', 'read', 'tree_text']

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

