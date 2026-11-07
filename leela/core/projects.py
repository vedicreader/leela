"Which folders Leela has open, and which it has had open lately. See `docs/desktop.md`."

from __future__ import annotations

import json, re, threading

from fastcore.xtras import Path, atomic_save
from kunda.pythons import nearest_marked

from .. import leela_cfg

__all__ = ['SESSION', 'SERVING', 'MAX_RECENT', 'PROJECT_MARKERS', 'nearest_marked', 'project_dir', 'workspace_for', 'loose_root',
           'title_part', 'title_folder', 'title_scope', 'window_title',
           'session', 'remember', 'note_folder', 'drop_folder',
           'last_folders', 'last_folder', 'recent_folders', 'forget_recent', 'serving', 'now_serving', 'served']

#: What makes a directory the project a surface acts on, rather than a directory inside one.
PROJECT_MARKERS = ('.git', 'pyproject.toml', 'setup.py', 'settings.ini')

def project_dir(start, stop=None):
    "The nearest checkout at or above `start`, not searched past `stop`. See `nearest_marked`."
    return nearest_marked(start, PROJECT_MARKERS, stop)[0]

def workspace_for(file, home=None):
    "The folder a single file opens in: its checkout, else its own folder. Never `home` or the root; None when that leaves nothing."
    f, home = Path(file).expanduser().resolve(), Path(home or Path.home()).resolve()
    barred = {home, Path(f.anchor)}
    d = nearest_marked(f, PROJECT_MARKERS, home)[0]
    if d is not None and d not in barred: return d
    return None if f.parent in barred else f.parent

def loose_root():
    "The empty folder Leela owns that stands for files opened outside any folder."
    (d := Path(leela_cfg)/'loose').mkdir(parents=True, exist_ok=True)
    return d.resolve()

def title_part(s, most=60):
    "One part of the window title: no control characters, never ` · ` inside, at most `most` characters. `titlePart` in keymap.js is the same."
    s = re.sub(r'[\x00-\x1f\x7f]+', ' ', str(s or ''))
    while ' · ' in s: s = s.replace(' · ', ' - ')
    return s.strip()[:most].strip()

def title_folder(root):
    "What the window title calls `root`: `loose` for the loose window, else the folder's name."
    if not root: return ''
    return 'loose' if Path(root).resolve() == (Path(leela_cfg)/'loose').resolve() else Path(root).name

def title_scope(kind=None, path=''):
    "The scope word a tab of `kind` at `path` gives the title before the page names the focused pane. `titleScope` in keymap.js is the same."
    if not kind: return 'files'
    if kind in ('vault', 'vaultwb'): return 'vault'
    if kind in ('notebook', 'web'): return kind
    ext = Path(path or '').suffix[1:].lower()
    return 'py' if ext == 'py' else f'editor:{ext}' if ext else 'editor'

def window_title(folder='', scope='files', prefix=''):
    "`[prefix · ]Leela · <folder> · <scope>`: the shape Sanketa reads, the scope always last."
    return ' · '.join(o for o in (prefix, 'Leela', title_part(folder), scope or 'files') if o)

#: The session a person opens. A test points `SESSION` at its own file; the guard below is about this one.
DEFAULT_SESSION = SESSION = leela_cfg/'desktop.json'
#: A running Leela's address. The desktop shell takes any free port, so nothing outside it could otherwise guess where to post.
SERVING = leela_cfg/'serving.json'
MAX_RECENT = 12

def _temporary(p):
    "Whether `p` is inside the system temp dir."
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
    "`paths` without the loose root, and without the temporary ones when this is the session a person actually opens."
    paths = [p for p in paths if Path(p) != loose_root()]
    if Path(SESSION) != DEFAULT_SESSION: return paths
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
