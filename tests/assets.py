"""Source text of the browser assets and the web layer, as single strings.

A large part of the suite asserts on the *text* of what leela ships to the browser --
that a keybinding exists, that a CSS class is defined, that a route renders a given id.
Those assertions were each reading one file:

    JS = (ROOT/'leela/web/static/lee-ide.js').read_text()

which quietly pins the architecture: `lee-ide.js` is one 6,000-line file *because* ~200
assertions say so, and the same for `web/app.py`. Splitting either one would fail a
hundred tests that have no opinion about file layout at all.

Reading a whole tree instead keeps the assertions honest about what they actually mean --
"the browser is served this behaviour", not "this behaviour lives in this file". A module
can move, split or be renamed without touching a single test; deleting the behaviour still
fails, which is what the assertions are for.

Everything here is read once at import and cached, so the whole suite pays for one pass
over the tree rather than one per test module.
"""

from functools import cache
from pathlib import Path

__all__ = ['ROOT', 'JS', 'CSS', 'EDITOR', 'TERM', 'SERVER', 'AGENT', 'read', 'tree_text']

ROOT = Path(__file__).resolve().parents[1]

# Sorted so the concatenation is byte-identical between runs and machines: a test that
# reports a character offset or slices around a match stays reproducible.
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
def _static(glob): return tree_text('leela/web/static', glob)

@cache
def _server():
    # Every Python module leela ships: the shell in `leela/app.py`, the blocks, and core.
    # Reading the whole tree rather than named files is the point -- a route can move from
    # `app.py` into a block, or a domain module into the block that owns it, without a test
    # edit, while deleting the behaviour still fails.
    return tree_text('leela', '*.py')


# Vendored bundles are minified third-party code (CodeMirror, xterm, htmx). They would add
# ~2MB of noise to every substring search and can produce false positives, so the browser
# text is leela's own hand-written assets only.
VENDOR = {'lee-cm6.js', 'lee-term.js', 'htmx.min.js'}

@cache
def _authored_js():
    d = ROOT/'leela/web/static'
    if not d.is_dir(): return ''
    return '\n'.join(p.read_text() for p in sorted(d.rglob('*.js')) if p.name not in VENDOR)


# PEP 562. Each corpus is a plain `str` -- `'x' in JS` and `JS.count(...)` are the whole
# API -- but building all of them at import would read the tree even for a run that
# selects one unrelated test. Resolving on first access and storing the result in the
# module dict means later lookups never reach this function.
_CORPORA = {'JS':     _authored_js,
            'CSS':    lambda: _static('*.css'),
            'EDITOR': lambda: read('leela/web/src/editor.js'),
            'TERM':   lambda: read('leela/web/src/term.js'),
            'SERVER': _server,
            'AGENT':  lambda: tree_text('leela/agent', '*.py')}


def __getattr__(name):
    if name not in _CORPORA: raise AttributeError(name)
    v = globals()[name] = _CORPORA[name]()
    return v
