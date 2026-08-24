"State one application session owns: open docs, running cells, the debugger, the journal."

from __future__ import annotations
import asyncio
from fastcore.basics import first
import gzip, hashlib, json, shutil, time, uuid
from pathlib import Path

__all__ = ['DocStore', 'DebugState', 'FileHistory', 'RunState', 'Trash', 'kernel_api']

#: How many versions of one file are kept. A person looking for what a tool overwrote is looking
#: at this morning, not at last month, and every version holds the whole file.
KEEP_PER_PATH = 60
#: Bodies past this are noted but not copied. A 70MB notebook saved through a day is gigabytes of
#: history for a file git already tracks, and copying it makes saving slow.
MAX_BODY = 2_000_000

async def kernel_api(session, path, params=None, timeout=15, tab=None):
    "Proxy an inspector call through the exact runtime `Run` would use."
    client = await session.runtime(tab)
    return await client.api(path, params, timeout) if client else None

class FileHistory:
    """Every version of a project file Leela saw, so a write it did not make is still recoverable.

    The loss happens before a commit, often from another process editing the same tree, so git
    cannot cover it. Bodies are stored once per distinct content.
    """
    def __init__(self, root, pinned=None):
        self.root = Path(root); self.path = self.root/'index.json'
        self.rows_ = []
        #: Digests something else still needs. Pruning a version must not take a body the journal
        #: is holding an operation open against.
        self.pinned = pinned or (lambda: ())
        self._load()
    def _load(self):
        try: self.rows_ = json.loads(self.path.read_text()).get('versions', [])
        except Exception: self.rows_ = []
    def _save(self):
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps({'versions': self.rows_}, ensure_ascii=False))
        tmp.replace(self.path)
    def _blob(self, text):
        digest = hashlib.sha256(text.encode('utf-8', 'replace')).hexdigest()[:16]
        p = self.root/'blobs'/f'{digest}.gz'
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(gzip.compress(text.encode('utf-8', 'replace')))
        return digest
    def stash(self, text):
        "Keep one body and return its digest. `None` for a file that was not there, or was too big."
        return None if text is None or len(str(text)) > MAX_BODY else self._blob(str(text))
    def body(self, digest):
        "A stashed body. A missing one is an error, never silently an empty file."
        if digest is None: return None
        p = self.root/'blobs'/f'{digest}.gz'
        if not p.exists(): raise ValueError('the stored body is gone')
        return gzip.decompress(p.read_bytes()).decode('utf-8', 'replace')
    def latest(self, path):
        return first(r for r in reversed(self.rows_) if r['path'] == str(path))
    def record(self, path, text, label='save'):
        "One version, or None when the file already reads exactly like this."
        if text is None: return None
        path = str(path)
        digest = hashlib.sha256(str(text).encode('utf-8', 'replace')).hexdigest()[:16]
        held = self.latest(path)
        if held is not None and held['blob'] == digest: return None
        # An enormous file is listed but not copied, and `kept` is what `text` reads to say so.
        big = len(str(text)) > MAX_BODY
        row = {'id': 'ver_' + uuid.uuid4().hex[:12], 'path': path, 'at': time.time(),
               'label': str(label), 'blob': digest if big else self._blob(str(text)),
               'bytes': len(str(text)), 'kept': not big}
        self.rows_.append(row); self._prune(path); self._save()
        return row
    def _prune(self, path):
        "Drop this path's oldest versions, and any body no surviving version names."
        mine = [r for r in self.rows_ if r['path'] == path]
        if len(mine) <= KEEP_PER_PATH: return
        drop = {r['id'] for r in mine[:-KEEP_PER_PATH]}
        self.rows_ = [r for r in self.rows_ if r['id'] not in drop]
        kept = {r['blob'] for r in self.rows_} | {d for d in self.pinned() if d}
        for p in (self.root/'blobs').glob('*.gz'):
            if p.stem not in kept:
                try: p.unlink()
                except OSError: pass
    def rows(self, path='', limit=60):
        "Versions newest first, of one file or of everything Leela has seen."
        rows = [r for r in self.rows_ if not path or r['path'] == str(path)]
        return [{k: v for k, v in r.items() if k != 'blob'} for r in rows[::-1][:int(limit)]]
    def text(self, version_id):
        "The body of one version. A missing body is an error, never silently an empty file."
        row = first(r for r in self.rows_ if r['id'] == str(version_id))
        if row is None: raise ValueError(f'no such version {version_id}')
        if not row.get('kept', True):
            raise ValueError(f"{row['path']} was {row['bytes']:,} bytes, too large to copy")
        p = self.root/'blobs'/f"{row['blob']}.gz"
        if not p.exists(): raise ValueError(f"the stored body for {row['path']} is gone")
        return gzip.decompress(p.read_bytes()).decode('utf-8', 'replace')
    def keep(self, path, before, after, label='change'):
        """Both sides of one change. The first `before` for a path is the only copy of what was
        there before Leela ever looked."""
        if before is not None and self.latest(path) is None:
            self.record(path, before, 'before the first change seen')
        return self.record(path, after, label)
    def row(self, version_id):
        "One version's listing, without its body."
        held = first(r for r in self.rows_ if r['id'] == str(version_id))
        return None if held is None else {k: v for k, v in held.items() if k != 'blob'}
    def paths(self, limit=200):
        "Which files have versions, most recently touched first."
        out = {}
        for r in reversed(self.rows_):
            row = out.setdefault(r['path'], {'path': r['path'], 'at': r['at'], 'versions': 0})
            row['versions'] += 1
        return list(out.values())[:int(limit)]

class DocStore:
    "Open notebooks and unsaved file text, keyed by tab."
    __slots__ = ('session', 'docs', 'buffers', 'bases', 'versions', 'run_locks')
    def __init__(self, session):
        self.session = session
        self.docs = {}
        self.buffers = {}
        self.bases = {}
        #: The `disk_version` each cached document was read at. What is held matches that, not what
        #: is on disk now, and a branch switch is the difference.
        self.versions = {}
        self.run_locks = {}
    @staticmethod
    def key(tab): return None if tab is None else (tab.path or tab.title)
    def current(self):
        "The notebook behind the active tab, or None when the active tab is not one."
        return self.docs.get(self.key(self.session.tab)) if self.session.tab else None
    def tab_for(self, ref):
        "The tab a request names, falling back to the active one. Survives a tab switch mid-flight."
        ref = str(ref or '')
        if not ref: return self.session.tab
        return first(t for t in self.session.tabs if self.key(t) == ref)
    def owner(self, ref):
        "`(tab, notebook, run_lock)` for a notebook request, or `(None, None, None)`."
        tab = self.tab_for(ref)
        if tab is None or tab.kind != 'notebook': return None, None, None
        lock = self.run_locks.setdefault(self.session.kernel_key(tab), asyncio.Lock())
        return tab, self.docs.get(self.key(tab)), lock
    def mark_all_stale(self):
        "A reset namespace makes every saved output historical, even though it stays useful."
        for nb in self.docs.values():
            for c in nb.cells: c.fresh = False
    def forget(self, key):
        "Drop everything held for one tab. Safe to call for a key that was never opened."
        for d in (self.docs, self.buffers, self.bases, self.versions): d.pop(key, None)

class DebugState:
    "Which kernel is paused, and where the frame it stopped in came from."
    __slots__ = ('kernel', 'origin_path', 'cell_id', 'direct_session', 'direct_task', 'direct_name')
    def __init__(self):
        self.kernel = None
        self.origin_path = ''
        self.cell_id = ''
        self.direct_session = None
        self.direct_task = None
        self.direct_name = ''
    @property
    def paused(self): return self.kernel is not None
    def clear(self):
        self.kernel, self.origin_path, self.cell_id = None, '', ''
    def clear_direct(self):
        self.direct_session, self.direct_task, self.direct_name = None, None, ''
    @property
    def cell_sources(self):
        "Temporary debug source path -> cell id, as recorded by the kernel that is paused."
        return getattr(self.kernel, '_debug_sources', {}) or {}

class RunState:
    "In-flight cell executions, so Stop stays aimed at the cell that started the work."
    __slots__ = ('cells',)
    def __init__(self): self.cells = {}
    def start(self, tab_key, cell_id, runtime, task): self.cells[(tab_key, cell_id)] = (runtime, task)
    def get(self, tab_key, cell_id): return self.cells.get((tab_key, cell_id), (None, None))
    def finish(self, tab_key, cell_id): return self.cells.pop((tab_key, cell_id), None)
    def running_in(self, tab_key):
        "Cell ids currently executing in one tab."
        return [cid for (tk, cid) in self.cells if tk == tab_key]

MAX_OPERATIONS = 200

class Trash:
    """Where a deleted file or folder goes, so deleting either is recoverable.

    A journal resource is text, and neither a directory nor a binary survives being one: a folder
    was recorded as nothing at all and a PNG came back as replacement characters. Moving the thing
    itself aside keeps whatever it was, and costs one rename instead of a copy.
    """
    def __init__(self, root): self.root = Path(root)
    def keep(self, path):
        "Move `path` aside whole and return the key that brings it back."
        p, key = Path(path), uuid.uuid4().hex[:12]
        d = self.root/key
        d.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), str(d/p.name))
        return key
    def held(self, key):
        "The path a key holds, or None when the trash no longer has it."
        d = self.root/str(key)
        return first(sorted(d.iterdir())) if d.is_dir() else None
    def restore(self, key, path):
        "Move what `key` holds back to `path`, and forget the key."
        src = self.held(key)
        if src is None: raise FileNotFoundError(f'the trash no longer holds {key}')
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(p))
        shutil.rmtree(self.root/str(key), ignore_errors=True)


class OperationJournal:
    "The last `MAX_OPERATIONS` workspace operations, on disk, newest last."
    def __init__(self, path, sandbox, history=None, trash=None):
        self.path, self.sandbox = Path(path), sandbox
        #: Deleted files and folders live here rather than as journal text, which cannot hold
        #: either. `None` leaves a delete unrecoverable, so `record` refuses to pretend otherwise.
        self.trash = trash
        #: Every write that reaches here is also kept version by version. Undo is one step back;
        #: after an agent or another editor has been through the tree a person wants this morning.
        self.history = history
        self.operations = []
        self._load()
    def _load(self):
        try: self.operations = json.loads(self.path.read_text()).get('operations', [])[-MAX_OPERATIONS:]
        except Exception: self.operations = []
    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps({'operations': self.operations[-MAX_OPERATIONS:]}, ensure_ascii=False))
        tmp.replace(self.path)
    def record(self, label, resources, kind='file', irreversible=(), moved=(), trashed=(),
               created=()):
        """Append one operation, or None when nothing actually changed.

        `resources` are content changes, `(path, before, after)`. The rest name where something went
        rather than what was in it, which is the only way to record a directory or a file that is
        not text: `moved` are `(new, old)` pairs, `trashed` are `(path, key)` for what was deleted,
        and `created` are paths this operation brought into being, which undo puts in the trash.
        """
        rows = [{'path': str(path), 'before': before, 'after': after}
                for path, before, after in resources if before != after]
        paths = ([{'path': str(new), 'from': str(old)} for new, old in moved] +
                 [{'path': str(path), 'at': 'trash', 'trash': str(key)} for path, key in trashed] +
                 [{'path': str(path), 'at': 'tree'} for path in created])
        if not rows and not paths and not irreversible: return None
        if self.history is not None:
            for row in rows:
                try: self.history.keep(row['path'], row['before'], row['after'], label)
                except Exception: pass       # a lost version must never fail the write itself
                # Bodies live in the history's blob store, not inline. This file is reloaded and
                # rewritten every operation.
                try:
                    before, after = self.history.stash(row['before']), self.history.stash(row['after'])
                    row['before_blob'], row['after_blob'] = before, after
                    # `kept` is false when a side existed and was too large to copy, so undo fails
                    # before it starts rather than halfway through.
                    row['kept'] = not any(body is not None and blob is None for body, blob in
                                          ((row['before'], before), (row['after'], after)))
                    del row['before'], row['after']
                except Exception: pass       # no blob, so the bodies stay where they are
        for prior in self.operations:
            if prior.get('undone'): prior['redoable'] = False
        op = {'id': 'op_' + uuid.uuid4().hex[:12], 'at': time.time(), 'label': str(label),
              'kind': kind, 'resources': rows + paths, 'irreversible': list(irreversible),
              'undone': False}
        self.operations.append(op); self.operations = self.operations[-MAX_OPERATIONS:]; self._save()
        return op
    def blobs(self):
        "Every body digest the journal still needs, so `FileHistory` does not prune one away."
        return {r[k] for op in self.operations for r in op.get('resources', [])
                for k in ('before_blob', 'after_blob') if r.get(k)}
    def _body(self, row, side):
        "One side of a resource: inline on an older operation, else out of the blob store."
        if side in row: return row[side]
        return self.history.body(row.get(f'{side}_blob')) if self.history is not None else None
    def rows(self, limit=50):
        "The newest `limit` operations, without their `before`/`after` bodies."
        return [{k: v for k, v in op.items() if k != 'resources'} |
                {'paths': [r['path'] for r in op.get('resources', [])],
                 'reversible': bool(op.get('resources')) and not op.get('undone'),
                 'redoable': bool(op.get('resources')) and op.get('undone') and op.get('redoable', True)}
                for op in reversed(self.operations[-int(limit):])]
    def _current(self, path):
        "One resource as it is on disk right now, or None when it is not there."
        p = self.sandbox._check(path)
        return p.read_text(encoding='utf-8', errors='replace') if p.exists() else None
    def _write(self, path, text):
        p = self.sandbox._check(path)
        if text is None:
            if p.exists(): p.unlink()
        else: self.sandbox.write(p, text)
    def _blocked(self, row, side):
        """Why this row cannot be reversed, or None.

        `side` names the state the tree has to be in already: undo checks `after` and then reverses
        to `before`, redo the other way about.
        """
        p = self.sandbox._check(row['path'])
        if 'at' in row:
            # A delete and a create are the same row read from opposite ends: the thing is either
            # in the tree or in the trash, and reversing it moves it across.
            wants = row['at'] if side == 'after' else ('tree' if row['at'] == 'trash' else 'trash')
            if wants == 'tree' and not p.exists(): return f'{p} is not there'
            if wants == 'trash':
                if p.exists(): return f'{p} is there again'
                if row.get('trash') and (self.trash is None or self.trash.held(row['trash']) is None):
                    return f'{p} is no longer in the trash'
            return None
        if 'from' in row:
            here, there = (p, self.sandbox._check(row['from'])) if side == 'after' else \
                          (self.sandbox._check(row['from']), p)
            if not here.exists(): return f'{here} is not there to move'
            if there.exists(): return f'{there} is in the way'
            return None
        return None if self._current(row['path']) == self._body(row, side) else str(p)
    def _reverse(self, row, side):
        "Put one row back to `side`: the text it held, or the place it was."
        if 'at' in row:
            p = self.sandbox._check(row['path'])
            wants = row['at'] if side == 'after' else ('tree' if row['at'] == 'trash' else 'trash')
            if wants == 'trash': row['trash'] = self.trash.keep(p)
            else: self.trash.restore(row['trash'], p)
            return None
        if 'from' in row:
            src, dst = (row['path'], row['from']) if side == 'before' else (row['from'], row['path'])
            d = self.sandbox._check(dst)
            d.parent.mkdir(parents=True, exist_ok=True)
            return shutil.move(str(self.sandbox._check(src)), str(d))
        return self._write(row['path'], self._body(row, side))
    def undo(self, operation_id=''):
        "Reverse one operation, named or the newest reversible one."
        back = reversed(self.operations)
        op = (first(x for x in back if x['id'] == operation_id) if operation_id else
              first(x for x in back if x.get('resources') and not x.get('undone')))
        if op is None: raise ValueError('no reversible workspace operation')
        if (big := [r['path'] for r in op['resources'] if not r.get('kept', True)]):
            raise ValueError('too large to have been copied, so it cannot be undone: ' + ', '.join(big))
        if op.get('undone'): raise ValueError('that operation was already undone')
        conflicts = [why for row in op['resources'] if (why := self._blocked(row, 'after'))]
        if conflicts: raise ValueError('changed after the operation: ' + ', '.join(conflicts))
        for row in reversed(op['resources']): self._reverse(row, 'before')
        op['undone'] = True; self._save(); return op
    def redo(self, operation_id=''):
        "Reapply one undone operation when every file still equals its restored text."
        op = (first(x for x in reversed(self.operations) if x['id'] == operation_id) if operation_id else
              first(x for x in self.operations if x.get('resources') and x.get('undone') and x.get('redoable', True)))
        if op is None: raise ValueError('no redoable workspace operation')
        if (big := [r['path'] for r in op['resources'] if not r.get('kept', True)]):
            raise ValueError('too large to have been copied, so it cannot be redone: ' + ', '.join(big))
        if not op.get('undone'): raise ValueError('that operation was not undone')
        conflicts = [why for row in op['resources'] if (why := self._blocked(row, 'before'))]
        if conflicts: raise ValueError('changed after the undo: ' + ', '.join(conflicts))
        for row in op['resources']: self._reverse(row, 'after')
        op['undone'] = False; self._save(); return op
