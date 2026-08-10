"""Which of your packages is installed, where from, and which one just raised.

When a deploy fails, the useful question is not "what is the traceback" -- it is on screen
-- but *whose code is that*. In a stack where you own dockeasy, vpseasy, cfeasy, gheasy and
the app, the answer decides which repository you open next, and reading it off a path in
`site-packages` is a small tax paid every single time.

So this does two things. `survey` reports the family: installed or not, version, where the
import actually resolves to, and whether that is an editable install pointing at a checkout
you have open. Version drift and a stale wheel shadowing a local edit are the two failures
that waste the most time, and both are visible in that one list.

`blame` reads a traceback out of a pipeline transcript and names the deepest frame belonging
to one of those packages -- then rewrites the path to the checkout in this workspace when
there is one. That is the whole point: a failed `cfeasy.setup_tunnel` should open
`cfeasy/core.py` in the repository you can fix, not the copy under `.venv` that the next
`uv sync` will overwrite.
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = ['FAMILY', 'survey', 'blame', 'frames', 'checkout_for']

# The packages this workspace is about. Anything else in a traceback is somebody else's
# code, and pointing at it would be a worse answer than pointing at nothing.
FAMILY = ['gheasy', 'dockeasy', 'vpseasy', 'cfeasy', 'leela', 'dhrishti', 'nbdev']

_FRAME = re.compile(r'File "([^"]+)", line (\d+), in (\S+)')


def _origin(name):
    "Where importing `name` would actually read from, without importing it."
    from importlib.util import find_spec
    try: spec = find_spec(name)
    except (ImportError, ValueError, ModuleNotFoundError): return None
    if spec is None: return None
    if spec.submodule_search_locations:
        for p in spec.submodule_search_locations: return Path(p)
    return Path(spec.origin) if spec.origin else None


def _version(name):
    from importlib import metadata
    try: return metadata.version(name)
    except Exception: return ''


def _vendored(path):
    "Is this path inside an installed environment rather than someone's working tree?"
    parts = set(Path(path).parts)
    return bool(parts & {'site-packages', 'dist-packages', '.venv', 'venv'})


def checkout_for(name, checkouts):
    """The workspace checkout that *is* this package, if one is open.

    Matched by the package directory it contains rather than by the repository's name: a
    repo can be called anything, and `<root>/<name>/__init__.py` is what makes it the source
    of `import <name>`.
    """
    for root in checkouts:
        root = Path(root).expanduser().resolve()
        for inner in (root/name, root/'src'/name):
            if (inner/'__init__.py').exists(): return str(root)
    return ''


def survey(names=(), checkouts=()):
    """One row per package: is it installed, which version, which copy runs, and is it yours.

    Two different facts, kept apart because confusing them is the failure. `source` is where
    an import *resolves* -- a wheel in site-packages or a working tree. `checkout` is whether
    this workspace has that package open. When both exist and disagree, an edit in the
    checkout does nothing at all until the environment is reinstalled, and that is precisely
    the half-hour this row is here to save.
    """
    roots = [Path(c).expanduser().resolve() for c in checkouts]
    rows = []
    for name in (list(names) or FAMILY):
        path = _origin(name)
        local = checkout_for(name, roots)
        from_source = bool(path) and not _vendored(path)
        rows.append({'name': name, 'installed': path is not None, 'version': _version(name),
                     'path': str(path or ''), 'checkout': local, 'editable': from_source,
                     'source': ('checkout' if from_source else 'site-packages') if path else '',
                     'shadowed': bool(local) and bool(path) and not from_source})
    return rows


def frames(text):
    "Every `File ..., line N, in f` in a traceback, oldest first, as the terminal printed it."
    return [{'file': m.group(1), 'line': int(m.group(2)), 'fn': m.group(3)}
            for m in _FRAME.finditer(str(text or ''))]


def _package_of(path, names):
    "The family package a file belongs to, by the directory it sits in."
    parts = Path(path).parts
    for name in names:
        if name in parts: return name
    return ''


def blame(text, names=(), checkouts=()):
    """Which package raised, and where to open it.

    The *deepest* family frame, not the first: a deploy fails inside `cfeasy.setup_tunnel`
    called from your `deploy.py`, and both are yours -- the one worth opening is the one that
    actually raised. When the raising frame is in an installed copy and the same package is
    checked out in this workspace, the path is rewritten to the checkout, because that is the
    file an edit survives in.

    `error` is the exception line, which is usually the whole story and is what a panel can
    show in one row.
    """
    text = str(text or '')
    names = list(names) or FAMILY
    roots = [Path(c).expanduser().resolve() for c in checkouts]
    found = None
    for frame in frames(text):
        pkg = _package_of(frame['file'], names)
        if pkg: found = frame | {'package': pkg}
    error = ''
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if line and not line.startswith(('File "', '^', '~', '|')) and ':' in line and '    ' not in line[:4]:
            error = line
            break
    if found is None:
        return {'package': '', 'file': '', 'line': 0, 'fn': '', 'error': error, 'open': ''}
    open_at = found['file']
    checkout = checkout_for(found['package'], roots)
    if checkout and not str(open_at).startswith(str(checkout)):
        # site-packages/cfeasy/core.py -> <checkout>/cfeasy/core.py
        parts = Path(found['file']).parts
        i = parts.index(found['package'])
        candidate = Path(checkout).joinpath(*parts[i:])
        if candidate.exists(): open_at = str(candidate)
    return {'package': found['package'], 'file': found['file'], 'line': found['line'],
            'fn': found['fn'], 'error': error, 'open': open_at, 'checkout': checkout or '',
            'version': _version(found['package'])}
