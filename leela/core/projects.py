"Which folders Leela has open, and which it has had open lately. See `docs/desktop.md`."

from __future__ import annotations

import json, threading

from fastcore.xtras import Path, atomic_save

from .. import leela_cfg

__all__ = ['SESSION', 'MAX_RECENT', 'session', 'remember', 'note_folder', 'drop_folder',
           'last_folders', 'recent_folders', 'forget_recent']

SESSION = leela_cfg/'desktop.json'
MAX_RECENT = 12

def _dir(p):
    "`p` resolved, or None when it is not an existing directory."
    try: p = Path(p).expanduser().resolve()
    except (OSError, ValueError): return None
    return str(p) if p.is_dir() else None

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
    with atomic_save(SESSION, mode='w') as f:
        json.dump({'folders': folders, 'recent': recent[:MAX_RECENT]}, f, indent=1)
    return folders

def remember(folders):
    "Replace the open set -- what the application launched with, or restored to."
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

def recent_folders(limit=MAX_RECENT):
    "What the welcome screen offers, most recently opened first."
    return _clean(session()['recent'])[:limit]

def forget_recent(path):
    "Drop one folder from the recent list, for a project that is finished."
    with _LOCK:
        d = session()
        gone = _clean([path]) or [str(Path(path).expanduser())]
        return _write(d['folders'], [f for f in _clean(d['recent']) if f not in gone])
