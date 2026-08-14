"""Which folders Leela has open, and which it has had open lately.

A command line answers "which project" every time it is typed. A double-clicked application
never gets asked, so it has to remember: this is the file that makes launching the packaged
app open the work you left, and the welcome screen offer the projects you actually use.

Two lists, deliberately separate. `folders` is the current set -- what to reopen next launch,
kept in step as roots are added and dropped. `recent` is a longer memory that outlives closing
a project, and is only ever appended to and pruned.

Nothing here decides anything. A folder that has been deleted or unmounted since is dropped on
read rather than offered and then failing, which is the only cleverness in the file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .. import leela_cfg

__all__ = ['SESSION', 'MAX_RECENT', 'session', 'remember', 'note_folder', 'drop_folder',
           'last_folders', 'recent_folders', 'forget_recent']

SESSION = leela_cfg/'desktop.json'
MAX_RECENT = 12


def _clean(paths):
    "Existing directories, resolved, de-duplicated, in the order given."
    out, seen = [], set()
    for p in paths:
        if not p: continue
        try: p = str(Path(p).expanduser().resolve())
        except (OSError, ValueError): continue
        if p in seen or not os.path.isdir(p): continue
        seen.add(p)
        out.append(p)
    return out


def session():
    "The remembered session. A missing or corrupt file reads as an empty one, never an error."
    try: d = json.loads(SESSION.read_text())
    except (OSError, ValueError): d = {}
    if not isinstance(d, dict): d = {}
    return {'folders': list(d.get('folders') or []), 'recent': list(d.get('recent') or [])}


def _write(folders, recent):
    SESSION.parent.mkdir(parents=True, exist_ok=True)
    SESSION.write_text(json.dumps({'folders': folders, 'recent': recent[:MAX_RECENT]}, indent=1))
    return folders


def remember(folders):
    "Replace the open set -- what the application launched with, or restored to."
    folders = _clean(folders)
    return _write(folders, _clean(folders + session()['recent']))


def note_folder(path):
    """Add one folder to the open set and the top of the recent list.

    Union rather than replace, because under `--app` each folder is its own `Workspace` and
    each would otherwise record itself as the whole session.
    """
    d = session()
    return _write(_clean(d['folders'] + [path]), _clean([path] + d['recent']))


def drop_folder(path):
    "Remove one folder from the open set. It stays in `recent`: closing is not forgetting."
    d = session()
    gone = _clean([path])
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
