"""Which folders Leela has open, and which it has had open lately.

A command line answers "which project" every time it is typed; a double-clicked application
is never asked, so it has to remember. Two lists, deliberately separate: `folders` is the
current set, kept in step as roots are added and dropped, and `recent` is a longer memory
that outlives closing a project. A folder that has been deleted or unmounted since is dropped
on read rather than offered and then failing.
"""

from __future__ import annotations

from fastcore.xtras import Path

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


def _write(folders, recent):
    SESSION.write_json({'folders': folders, 'recent': recent[:MAX_RECENT]}, indent=1)
    return folders


def remember(folders):
    "Replace the open set -- what the application launched with, or restored to."
    folders = _clean(folders)
    return _write(folders, _clean(folders + session()['recent']))


def note_folder(path):
    "Add one folder to the open set and the top of the recent list."
    # Union rather than replace: under `--app` each folder is its own `Workspace`, and each
    # would otherwise record itself as the whole session.
    d = session()
    return _write(_clean(d['folders'] + [path]), _clean([path] + d['recent']))


def drop_folder(path):
    "Remove one folder from the open set. It stays in `recent`: closing is not forgetting."
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
    d = session()
    gone = _clean([path]) or [str(Path(path).expanduser())]
    return _write(d['folders'], [f for f in _clean(d['recent']) if f not in gone])
