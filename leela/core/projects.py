"Which folders Leela has open, and which it has had open lately. See `docs/desktop.md`."

from __future__ import annotations

import json, threading

from fastcore.xtras import Path, atomic_save

from .. import leela_cfg

__all__ = ['SESSION', 'SERVING', 'MAX_RECENT', 'PROJECT_MARKERS', 'nearest_marked', 'project_dir',
           'session', 'remember', 'note_folder', 'drop_folder',
           'last_folders', 'last_folder', 'recent_folders', 'forget_recent', 'serving', 'now_serving', 'served']

#: What makes a directory the project a surface acts on, rather than a directory inside one.
PROJECT_MARKERS = ('.git', 'pyproject.toml', 'setup.py', 'settings.ini')

def nearest_marked(start, markers, stop=None):
    """The nearest directory at or above `start` holding one of `markers`, and the marker it holds.

    One walk, because a workspace has several answers keyed to the same question and they have to
    agree: which interpreter a kernel starts in, which index a search reads, which checkout a
    release runs in. `stop` is the open folder, and the walk does not pass it: what is above the
    workspace belongs to something else. `markers` are relative paths, so `.venv/bin/python` asks
    about a file and `.git` asks about a directory.
    """
    try: start = Path(start).resolve()
    except (OSError, ValueError): return None, None
    try: stop = Path(stop).resolve() if stop else None
    except (OSError, ValueError): stop = None
    for d in (start, *start.parents):
        for m in markers:
            if (hit := d/m).exists(): return d, hit
        if stop is not None and d == stop: break
    return None, None

def project_dir(start, stop=None):
    "The nearest checkout at or above `start`, not searched past `stop`. See `nearest_marked`."
    return nearest_marked(start, PROJECT_MARKERS, stop)[0]

#: The session a person opens. A test points `SESSION` at its own file; the guard below
#: is about this one.
DEFAULT_SESSION = SESSION = leela_cfg/'desktop.json'
#: A running Leela's address. The desktop shell takes whatever port is free, so nothing outside
#: it could otherwise guess where to post.
SERVING = leela_cfg/'serving.json'
MAX_RECENT = 12

def _temporary(p):
    """Whether `p` is inside the system temp dir.

    A folder there is a test's, a probe's or an unpacked archive's, and none of them is a project a
    person wants reopened next launch. One of them written into the session is a folder they then
    have to close by hand, in every window.
    """
    import tempfile
    try: p, root = Path(p).expanduser().resolve(), Path(tempfile.gettempdir()).resolve()
    except (OSError, ValueError): return False
    return p == root or root in p.parents

def _dir(p):
    "`p` resolved, or None when it is not an existing directory."
    try: p = Path(p).expanduser().resolve()
    except (OSError, ValueError): return None
    return str(p) if p.is_dir() else None

def _lasting(paths):
    """`paths` without the temporary ones, when this is the session a person actually opens.

    A test names its own file and may keep whatever it likes in it. The real session is the one that
    must never fill up with a suite's scratch folders, which is how eleven `tmp…` directories came to
    be sitting in somebody's window.
    """
    if Path(SESSION) != DEFAULT_SESSION: return list(paths)
    return [p for p in paths if not _temporary(Path(p))]

def _clean(paths):
    "Existing directories, resolved, de-duplicated, in the order given."
    return list(dict.fromkeys(d for p in paths if p and (d := _dir(p))))

def session():
    "The remembered session. A missing or corrupt file reads as an empty one, never an error."
    try: d = SESSION.read_json()
    except (OSError, ValueError): d = {}
    if not isinstance(d, dict): d = {}
    return {'folders': list(d.get('folders') or []), 'recent': list(d.get('recent') or [])}

# Every change reads the whole file and writes it back, from request threads that overlap.
_LOCK = threading.RLock()

def _write(folders, recent):
    folders, recent = _lasting(folders), _lasting(recent)
    with atomic_save(SESSION, mode='w') as f:
        json.dump({'folders': folders, 'recent': recent[:MAX_RECENT]}, f, indent=1)
    return folders

def remember(folders):
    "Replace the open set: what the application launched with, or restored to."
    folders = _clean(folders)
    with _LOCK: return _write(folders, _clean(folders + session()['recent']))

def note_folder(path):
    "Add one folder to the open set and the top of the recent list. Union, not replace."
    with _LOCK:
        d = session()
        return _write(_clean(d['folders'] + [path]), _clean([path] + d['recent']))

def drop_folder(path):
    "Remove one folder from the open set. It stays in `recent`: closing is not forgetting."
    with _LOCK:
        d, gone = session(), _clean([path])
        return _write([f for f in _clean(d['folders']) if f not in gone], _clean(d['recent']))

def last_folders():
    "What to reopen when the application is launched with no arguments."
    return _clean(session()['folders'])

def last_folder():
    "The one folder a launch with no arguments reopens. `note_folder` appends, so it is the last."
    return _clean(session()['folders'])[-1:]

def recent_folders(limit=MAX_RECENT):
    "What the welcome screen offers, most recently opened first."
    return _clean(session()['recent'])[:limit]

def forget_recent(path):
    "Drop one folder from the recent list, for a project that is finished."
    with _LOCK:
        d = session()
        gone = _clean([path]) or [str(Path(path).expanduser())]
        return _write(d['folders'], [f for f in _clean(d['recent']) if f not in gone])

def now_serving(host, port, folders=()):
    "Write down where this workspace is answering, and return the record."
    import os, time
    d = {'host': str(host), 'port': int(port), 'pid': os.getpid(), 'at': time.time(),
         'url': f'http://{host}:{int(port)}/', 'folders': _clean(folders)}
    try:
        with atomic_save(SERVING, mode='w') as f: json.dump(d, f, indent=1)
    except OSError: pass
    return d

def served():
    "Forget the address. A stale one sends the next caller to a port somebody else now holds."
    try: SERVING.unlink()
    except OSError: pass

def serving():
    "Where a running Leela is answering, or None."
    # The pid is checked, not trusted: a killed workspace leaves a file naming somebody else's port.
    import os
    try: d = SERVING.read_json()
    except (OSError, ValueError): return None
    if not isinstance(d, dict) or not d.get('port'): return None
    try: os.kill(int(d.get('pid') or 0), 0)
    except (OSError, ValueError, TypeError): return None
    return d
