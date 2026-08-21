"""Dated copies of the state Leela cannot regenerate, and the retention that keeps them useful.

The conversation log, its session and branch sidecars, saved workspaces, keymaps and notes are all
small files that are only ever appended to or replaced in place. One bad write loses them, and
nothing else in the system holds a second copy -- so this does, on a cadence and before anything
overwrites the log.

Each dated copy is one gzipped tar with a JSON manifest beside it, and what goes into it is a
person's choice: journals alone are tens of megabytes, and five uncompressed copies of everything
was a third of a gigabyte.
"""

import io, json, os, shutil, tarfile, threading, time
from datetime import datetime
from tempfile import TemporaryDirectory
from fastcore.all import Path

from .. import leela_cfg

__all__ = ['AGENT_ENTRIES', 'ARCHIVE', 'BACKUP_DIR', 'CADENCES', 'ENTRIES', 'PRECIOUS',
           'agent_source', 'backup_cadence',
           'backup_dir', 'backup_settings', 'backups', 'chosen_entries', 'clean_backups',
           'clean_dates', 'create_backup', 'due', 'entry_source', 'guard', 'restore', 'run_backup',
           'schedule_backups']

BACKUP_DIR = 'backups'
STAMP = '%Y%m%d_%H%M%S'
ARCHIVE = '.tar.gz'

#: What a person cannot get back by rebuilding, and what to call it on the settings page. Caches,
#: logs and indexes are deliberately absent -- they regenerate, and copying them makes a backup too
#: big to keep many of. Everything here is a path under the config dir except `vault`.
ENTRIES = {
    'agent-history.jsonl': 'conversations',
    'agent-sessions.json': 'conversation titles',
    'agent-branches.json': 'conversation branches',
    'inline-history.jsonl': 'inline edit history',
    'workspace.json': 'open workspace',
    'settings.json': 'settings',
    'keys.json': 'keymap',
    'vaults.json': 'vault list',
    'feeds.json': 'feeds',
    'desktop.json': 'desktop layout',
    'agent-plans': 'plans',
    'timelines': 'timelines',
    'journals': 'journals',
    'memory': 'block memory',
    'workspaces': 'saved workspaces',
    'vault': 'vault memory (outside the config dir)',
}

#: Chosen until a person chooses otherwise. The vault is left out: it is a live database in its own
#: directory, and a restore of it writes outside the config dir.
PRECIOUS = tuple(k for k in ENTRIES if k != 'vault')

#: How often, in hours. `off` keeps the pre-write guard and nothing else, because losing the log to
#: a bad write is the failure this exists for and it does not wait for a schedule.
CADENCES = {'off': 0, 'hourly': 1, 'sixhourly': 6, 'daily': 24, 'weekly': 168}

def stamp(when=None): return (when or datetime.now()).strftime(STAMP)
def _when(name):
    try: return datetime.strptime(str(name), STAMP)
    except ValueError: return None

def _stem(name):
    name = str(name)
    return name[:-len(ARCHIVE)] if name.endswith(ARCHIVE) else name

def _top(name): return str(name).split('/')[0]

def backup_dir(cfg=None): return Path(cfg or leela_cfg)/BACKUP_DIR

#: The entries Ramabana writes, which `agent.configFolder` can move out of Leela's config dir.
#: A backup that kept copying the old location would protect an empty log.
AGENT_ENTRIES = ('agent-history.jsonl', 'agent-sessions.json', 'agent-branches.json', 'agent-plans')

def agent_source(cfg=None):
    """Where the agent's own files are, which is not Leela's config dir once a folder is shared.

    Only a folder that was actually chosen moves anything: with the setting empty this is the
    config dir it has always been, so nothing about an existing install changes.
    """
    try:
        from ..blocks.settings.settings import Settings
        folder = str((Settings().effective().get('agent') or {}).get('configFolder') or '').strip()
        if folder: return Path(folder).expanduser()
    except Exception: pass
    return Path(cfg or leela_cfg)

def entry_source(name, cfg=None, agent=None):
    "Where an entry lives. Everything but the vault is a path under a config dir."
    if name in AGENT_ENTRIES and agent is not None: return Path(agent)/name
    if name != 'vault': return Path(cfg or leela_cfg)/name
    env = os.getenv('VISHALAKSHI_VAULT')
    return Path(env).parent if env else Path.home()/'.vishalakshi'

def backup_settings():
    "The `backups` block of the effective settings, with the defaults when nothing is saved."
    try:
        from ..blocks.settings.settings import Settings
        held = (Settings().effective().get('backups') or {})
    except Exception: held = {}
    bands = str(held.get('ageBands') or '2,14,60')
    try: ages = tuple(int(x.strip()) for x in bands.split(',') if x.strip())
    except ValueError: ages = (2, 14, 60)
    inc = held.get('include')
    return {'cadence': str(held.get('cadence') or 'daily'), 'ages': ages or (2, 14, 60),
            'keep': max(1, int(held.get('keepNewest') or 5)),
            'include': _known(inc) if isinstance(inc, (list, tuple)) else PRECIOUS}

def _known(names):
    "The named entries in catalogue order; anything unknown is dropped rather than guessed at."
    want = {str(x) for x in (names or [])}
    return tuple(k for k in ENTRIES if k in want)

def chosen_entries(include=None):
    "What to copy: what was asked for, else what settings hold."
    return _known(include) if include is not None else backup_settings()['include']

def backup_cadence(): return backup_settings()['cadence']

def _manifest(root, name): return Path(root)/f'{name}.json'

def _read_manifest(path):
    try: return json.loads(Path(path).read_text())
    except Exception: return {}

def _scan(arc):
    "What an archive holds, for one written before its manifest or with the manifest lost."
    try:
        with tarfile.open(arc, 'r:gz') as tar: names = [m.name for m in tar.getmembers() if m.isfile()]
    except Exception: return {'files': 0, 'entries': []}
    return {'files': len(names), 'entries': sorted({_top(n) for n in names if _top(n) != '.reason'})}

def _archive_info(arc, name, when):
    held = _read_manifest(_manifest(arc.parent, name)) or _scan(arc)
    return {'name': name, 'at': when.timestamp(), 'files': int(held.get('files') or 0),
            'bytes': arc.stat().st_size, 'reason': str(held.get('reason') or ''),
            'entries': list(held.get('entries') or []), 'archived': True}

def _folder_info(d, name, when):
    files = [f for f in d.rglob('*') if f.is_file()]
    return {'name': name, 'at': when.timestamp(), 'files': len(files),
            'bytes': sum(f.stat().st_size for f in files),
            'reason': (d/'.reason').read_text().strip() if (d/'.reason').exists() else '',
            'entries': sorted(p.name for p in d.iterdir() if p.name != '.reason'), 'archived': False}

def backups(cfg=None):
    "Every dated backup, oldest first: the archives, and any folder copy taken before them."
    root = backup_dir(cfg)
    if not root.exists(): return []
    out = {}
    for p in sorted(root.iterdir()):
        name = _stem(p.name)
        when = _when(name)
        if when is None: continue
        if p.name.endswith(ARCHIVE): out[name] = _archive_info(p, name, when)
        elif p.is_dir(): out.setdefault(name, _folder_info(p, name, when))
    return [out[k] for k in sorted(out)]

def create_backup(src, dest, reason='', dry_run=False, include=None, agent=None):
    "Archive every chosen path under `src` into one dated `.tar.gz`. Returns the file, or None."
    src, dest = Path(src), Path(dest)
    picked = [(n, p) for n in chosen_entries(include) if (p := entry_source(n, src, agent)).exists()]
    if not picked: return None
    out = dest/f'{stamp()}{ARCHIVE}'
    if dry_run: return out
    dest.mkdir(parents=True, exist_ok=True)
    held, files = [], 0
    with tarfile.open(out, 'w:gz') as tar:
        for name, path in picked:
            try: files += _add_entry(tar, name, path)
            except Exception: continue   # one unreadable file must not cost the rest of the copy
            held.append(name)
        if reason: _add_text(tar, '.reason', str(reason).strip() + '\n')
    _manifest(dest, _stem(out.name)).write_text(json.dumps(
        {'reason': str(reason or '').strip(), 'files': files, 'entries': held}) + '\n')
    return out

SQLITE_SIDECARS = ('-wal', '-shm')

def _add_entry(tar, name, path):
    """Add one entry, taking any live database through SQLite rather than copying its files.

    A `.db` in WAL mode is three files that change independently, so copying them one after another
    can capture a set that never existed together. `-shm` is worse than useless in a copy: SQLite
    rebuilds it, and a stale one confuses recovery. The backup API hands over one consistent file.
    """
    if path.is_file():
        if path.suffix == '.db': return _add_sqlite(tar, name, path)
        tar.add(path, arcname=name); return 1
    tar.add(path, arcname=name, recursive=False)   # the entry itself, so the layout is unchanged
    files = 0
    for f in sorted(path.rglob('*')):
        if not f.is_file() or f.name.endswith(SQLITE_SIDECARS): continue
        arc = f'{name}/{f.relative_to(path)}'
        files += _add_sqlite(tar, arc, f) if f.suffix == '.db' else (tar.add(f, arcname=arc) or 1)
    return files

def _add_sqlite(tar, name, db):
    "One consistent copy of a live database, or the file as it lies if it is not one."
    import sqlite3, tempfile
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)/db.name
        try:
            with sqlite3.connect(f'file:{db}?mode=ro', uri=True) as src, sqlite3.connect(out) as dst:
                src.backup(dst)
        except Exception:
            tar.add(db, arcname=name); return 1
        tar.add(out, arcname=name)
    return 1

def _add_text(tar, name, text):
    data = text.encode()
    info = tarfile.TarInfo(name); info.size, info.mtime = len(data), int(time.time())
    tar.addfile(info, io.BytesIO(data))

def clean_dates(dates, now=None, max_ages=(2, 14, 60), k=5):
    """Which dated names to keep: the oldest still inside each age band, plus the newest `k`.

    Tiered rather than "last n", so a mistake noticed a month later still has something to go back
    to, without keeping every copy ever made.
    """
    now, keep = now or datetime.now(), []
    dated = sorted([d for d in dates if _when(d) is not None])
    for age in max_ages:
        inside = [d for d in dated if (now - _when(d)).days < age]
        if inside: keep.append(inside[0])
    keep.extend(dated[-k:])
    return sorted(set(keep))

def clean_backups(dest, max_ages=(2, 14, 60), k=5, dry_run=False):
    "Remove the dated copies `clean_dates` did not choose, archive or folder. Returns what went."
    root = Path(dest)
    if not root.exists(): return []
    have = {}
    for p in root.iterdir():
        name = _stem(p.name)
        if _when(name) is None: continue
        if p.name.endswith(ARCHIVE) or p.is_dir(): have.setdefault(name, []).append(p)
    keep, gone = clean_dates(list(have), max_ages=max_ages, k=k), []
    for name, paths in have.items():
        if name in keep: continue
        if not dry_run:
            failed = False
            for p in paths + [_manifest(root, name)]:
                try:
                    if p.is_dir(): shutil.rmtree(p)
                    elif p.exists(): p.unlink()
                except Exception: failed = True
            if failed: continue
        gone.append(name)
    return gone

def run_backup(cfg=None, reason='', max_ages=(2, 14, 60), k=5, dry_run=False, include=None):
    "One dated archive, then the pruning. Never raises: a failed backup must not stop the app."
    cfg = Path(cfg or leela_cfg)
    out = {'ok': False, 'name': '', 'removed': [], 'problem': ''}
    try:
        made = create_backup(cfg, backup_dir(cfg), reason=reason, dry_run=dry_run, include=include,
                             agent=agent_source(cfg))
        out['ok'], out['name'] = made is not None, _stem(made.name) if made else ''
        if made is None:
            out['problem'] = ('nothing is selected to back up' if not chosen_entries(include)
                              else 'there is nothing to back up yet')
    except Exception as e: out['problem'] = f'{type(e).__name__}: {e}'
    try: out['removed'] = clean_backups(backup_dir(cfg), max_ages, k, dry_run)
    except Exception as e: out['problem'] = out['problem'] or f'{type(e).__name__}: {e}'
    return out

def due(cadence='daily', cfg=None, now=None):
    "Whether the chosen cadence has come round again. `off` is never due."
    hours = CADENCES.get(str(cadence), 0)
    if not hours: return False
    have = backups(cfg)
    if not have: return True
    return (now or time.time()) - have[-1]['at'] >= hours * 3600

def guard(path, cfg=None, reason='before an overwrite'):
    """A copy taken because something is about to replace `path`, kept apart from the cadence.

    The failure this exists for is one write to the conversation log, so the copy has to happen
    on that write rather than on a timer that may be hours away.
    """
    path = Path(path)
    if not path.exists() or not path.stat().st_size: return None
    root = backup_dir(cfg)/'guard'
    root.mkdir(parents=True, exist_ok=True)
    out = root/f'{path.name}.{stamp()}'
    try: shutil.copy2(path, out)
    except Exception: return None
    kept = sorted(p for p in root.iterdir() if p.name.startswith(path.name + '.'))
    for old in kept[:-10]:               # ten is enough to notice and act
        try: old.unlink()
        except Exception: pass
    return out

def restore(name, cfg=None, only=None, dry_run=False):
    """Put a dated backup back, keeping a guard copy of whatever it replaces.

    Restoring is itself a write over live state, so it takes its own copy first: a restore of the
    wrong backup must not be the second thing that loses a conversation. `only` names the entries
    to put back, and only those come out of the archive.
    """
    cfg, name = Path(cfg or leela_cfg), _stem(name)
    arc, folder = backup_dir(cfg)/f'{name}{ARCHIVE}', backup_dir(cfg)/name
    if arc.is_file(): return _from_archive(arc, name, cfg, only, dry_run)
    if folder.is_dir(): return _from_folder(folder, name, cfg, only, dry_run)
    raise FileNotFoundError(f'no backup named {name}')

def _wanted(names, only):
    only = {str(x) for x in only} if only else None
    return [n for n in sorted(set(names)) if n != '.reason' and (not only or n in only)]

def _from_archive(arc, name, cfg, only=None, dry_run=False):
    with tarfile.open(arc, 'r:gz') as tar:
        members = tar.getmembers()
        wanted = _wanted([_top(m.name) for m in members], only)
        if not wanted: raise ValueError(f'backup {name} holds nothing to restore')
        if dry_run: return {'name': name, 'restored': wanted, 'files': len(wanted)}
        want = set(wanted)
        with TemporaryDirectory() as td:
            _extract(tar, td, [m for m in members if _top(m.name) in want])
            done = _place(Path(td), wanted, cfg, name)
    return {'name': name, 'restored': done, 'files': len(wanted)}

def _extract(tar, where, members):
    try: tar.extractall(where, members=members, filter='data')
    except TypeError: tar.extractall(where, members=members)

def _from_folder(folder, name, cfg, only=None, dry_run=False):
    "A copy taken before the archives, restored from the folder tree it still is."
    wanted = _wanted([p.name for p in folder.iterdir()], only)
    if not wanted: raise ValueError(f'backup {name} holds nothing to restore')
    if dry_run: return {'name': name, 'restored': wanted, 'files': len(wanted)}
    return {'name': name, 'restored': _place(folder, wanted, cfg, name), 'files': len(wanted)}

def _place(src, names, cfg, why):
    "Put each named entry back where it came from, guarding the file it replaces."
    done = []
    for name in names:
        path, target = Path(src)/name, entry_source(name, cfg, agent_source(cfg))
        if not path.exists(): continue
        if target.is_file(): guard(target, cfg, reason=f'replaced by {why}')
        try:
            if path.is_dir(): shutil.copytree(path, target, dirs_exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
            done.append(name)
        except Exception: pass
    return done

def schedule_backups(cadence='daily', cfg=None, interval=900):
    """A daemon thread that takes a copy whenever the cadence is due. Returns a stop function.

    Checked often and taken rarely, so a long-running window still gets its daily copy without the
    app having to know when it started.
    """
    stop = threading.Event()
    if not CADENCES.get(str(cadence), 0): return stop.set
    def loop():
        while not stop.wait(1):
            if due(cadence, cfg): run_backup(cfg, reason=f'{cadence} backup')
            if stop.wait(interval): return
    threading.Thread(target=loop, daemon=True, name='leela-backups').start()
    return stop.set
