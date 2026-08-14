'Which of your packages is installed, where from, and which one just raised.'

from __future__ import annotations

import re
from pathlib import Path

from fastcore.basics import first, ifnone

__all__ = ['FAMILY', 'survey', 'blame', 'frames', 'checkout_for', 'installed']

FAMILY = ['gheasy', 'dockeasy', 'vpseasy', 'cfeasy', 'leela', 'dhrishti', 'nbdev']

_FRAME = re.compile(r'File "([^"]+)", line (\d+), in (\S+)')


def installed(name):
    "Is `name` importable, without importing it?"
    from importlib.util import find_spec
    try: return find_spec(name) is not None
    except (ImportError, ValueError): return False


def _origin(name):
    "Where importing `name` would actually read from, without importing it."
    from importlib.util import find_spec
    try: spec = find_spec(name)
    except (ImportError, ValueError, ModuleNotFoundError): return None
    if spec is None: return None
    where = first(spec.submodule_search_locations or ()) or spec.origin
    return Path(where) if where else None


def _version(name):
    from importlib import metadata
    try: return metadata.version(name)
    except Exception: return ''


def _vendored(path):
    "Is this path inside an installed environment rather than someone's working tree?"
    parts = set(Path(path).parts)
    return bool(parts & {'site-packages', 'dist-packages', '.venv', 'venv'})


def _roots(checkouts): return [Path(c).expanduser().resolve() for c in checkouts]


def checkout_for(name, checkouts):
    "The open checkout that *is* this package, matched by `<root>/<name>/__init__.py`, not repo name."
    for root in _roots(checkouts):
        for inner in (root/name, root/'src'/name):
            if (inner/'__init__.py').exists(): return str(root)
    return ''


def _row(name, roots):
    "One package: where an import lands, and whether that copy is the open checkout."
    path = _origin(name)
    local = checkout_for(name, roots)
    from_source = bool(path) and not _vendored(path)
    return {'name': name, 'installed': path is not None, 'version': _version(name),
            'path': str(path or ''), 'checkout': local, 'editable': from_source,
            'source': ('checkout' if from_source else 'site-packages') if path else '',
            'shadowed': bool(local) and bool(path) and not from_source}


def survey(names=(), checkouts=()):
    "One row each: installed, version, the copy an import resolves to, and whether a checkout is shadowed."
    roots = _roots(checkouts)
    return [_row(name, roots) for name in (list(names) or FAMILY)]


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


def _is_error(line):
    "A line that reads like `SomeError: message` rather than a frame or a caret marker."
    return bool(line) and not line.startswith(('File "', '^', '~', '|')) and ':' in line and '    ' not in line[:4]


def blame(text, names=(), checkouts=()):
    "Which package raised (the deepest family frame) and where to open it, preferring a checkout."
    text = str(text or '')
    names = list(names) or FAMILY
    roots = _roots(checkouts)
    family = [f | {'package': pkg} for f in frames(text)
              if (pkg := _package_of(f['file'], names))]
    found = family[-1] if family else None
    error = ifnone(first((l.strip() for l in reversed(text.strip().splitlines())), _is_error), '')
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
