'Which of your packages is installed, where from, and which one just raised.'

from __future__ import annotations

import re
from pathlib import Path

__all__ = ['FAMILY', 'survey', 'blame', 'frames', 'checkout_for']

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
    "The open checkout that *is* this package, matched by `<root>/<name>/__init__.py`, not repo name."
    for root in checkouts:
        root = Path(root).expanduser().resolve()
        for inner in (root/name, root/'src'/name):
            if (inner/'__init__.py').exists(): return str(root)
    return ''


def survey(names=(), checkouts=()):
    "One row each: installed, version, the copy an import resolves to, and whether a checkout is shadowed."
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
    """The family package a file belongs to.

    Inside an environment it is the component right after `site-packages` and nothing else: a
    venv at `~/code/leela/.venv` puts `leela` in every installed package's path, so matching
    anywhere blames Leela for the Cloudflare SDK. Outside one, the last match wins.
    """
    parts = Path(path).parts
    for marker in ('site-packages', 'dist-packages'):
        if marker in parts:
            i = parts.index(marker) + 1
            found = parts[i] if i < len(parts) else ''
            return found if found in names else ''
    for part in reversed(parts):
        if part in names: return part
    return ''


def blame(text, names=(), checkouts=()):
    "Which package raised (the deepest family frame) and where to open it, preferring a checkout."
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
        parts = Path(found['file']).parts
        i = parts.index(found['package'])
        candidate = Path(checkout).joinpath(*parts[i:])
        if candidate.exists(): open_at = str(candidate)
    return {'package': found['package'], 'file': found['file'], 'line': found['line'],
            'fn': found['fn'], 'error': error, 'open': open_at, 'checkout': checkout or '',
            'version': _version(found['package'])}
