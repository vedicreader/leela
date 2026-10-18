"Files: the tree, the folder picker, and the four mutations."

from __future__ import annotations
import os, re

from fastcore.all import Path, first

from fasthtml.common import Div

from ... import errstr
from ...core.web import fail, off_loop, sse, unless_gone
from ...core.text import fuzzy_rank
from .fs import lang_for
from .ui import files_panel, git_ignored, git_tree_state, stale_tree, tree_node
from ..tabs.app import disk_version
from ...core.web import diff_payload
from ..settings.settings import start_folder

__all__ = ['CAPS', 'connect', 'SERVED_TYPES']

SERVED_TYPES = {'.pdf': 'application/pdf', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.gif': 'image/gif', '.webp': 'image/webp', '.svg': 'image/svg+xml', '.ico': 'image/x-icon',
    '.bmp': 'image/bmp', '.wav': 'audio/wav', '.mp3': 'audio/mpeg', '.m4a': 'audio/mp4',
    '.ogg': 'audio/ogg', '.flac': 'audio/flac', '.aac': 'audio/aac', '.mp4': 'video/mp4',
    '.webm': 'video/webm', '.ogv': 'video/ogg', '.mov': 'video/quicktime'}

CAPS = ('fs', 'fs_watch', 'journal', 'docs')

def _forget(ctx, *paths):
    "Drop server state for paths that have just moved or gone."
    for path in paths:
        if not path: continue
        ctx.docs.forget(str(path))
        for tab in ctx.session.tabs:
            if tab.path and (tab.path == str(path) or Path(tab.path).is_relative_to(Path(path))):
                ctx.docs.forget(tab.path)      # a folder's cache is keyed per file inside it
                yield tab

def _freshen(ctx, paths, resync=False):
    "Drop the cached copy of an open, unedited document that changed on disk."
    changed = {str(p) for p in paths}
    for tab in ctx.session.tabs:
        if not tab.path or tab.dirty: continue
        if not (resync or tab.path in changed): continue
        # A save Leela made is not a change to follow. `versions` is stamped whenever a document is
        # read or written.
        if ctx.docs.versions.get(tab.path) == disk_version(tab.path): continue
        ctx.docs.forget(tab.path)

def _dotted(fs, p):
    "Whether `p` sits under a dot-folder, or is a dotfile, below the root it is in."
    root = first(r for r in fs.roots if Path(p).is_relative_to(r))
    return root is not None and any(s.startswith('.') for s in Path(p).relative_to(root).parts)

def _sort_changes(ctx, paths, hidden=False):
    """`(shown, tracked)`: what the tree or a tab can show, and of that, what git can see.
    An indexer writing under `.kosha` or a log under an ignored `data/` redrew the tree and re-ran
    git in every repository once a second."""
    tabs = {t.path for t in ctx.session.tabs if t.path}
    shown = [p for p in paths if p in tabs or hidden or not _dotted(ctx.fs, p)]
    return shown, [p for p in shown if not git_ignored(ctx.fs, p)]

def _batch(items):
    "What to call a batch in a journal label: the one name, or how many there were."
    if len(items) == 1: return Path(items[0][0] if isinstance(items[0], tuple) else items[0]).name
    return f'{len(items)} items'

def _closed(ctx, path):
    "Close every tab on `path` or under it, rightmost first, so no index shifts under the rest."
    tabs = list(_forget(ctx, path))
    for tab in sorted(tabs, key=lambda t: ctx.session.tabs.index(t), reverse=True):
        ctx.session.close(ctx.session.tabs.index(tab))
    return [t.path for t in tabs]

def connect(app, ctx):
    rt = app.route
    @rt('/tree')
    def tree(path: str, hidden: bool = False):
        try:
            state = git_tree_state(ctx.fs)
            return tuple(tree_node(e, state, hidden) for e in ctx.fs.ls(path, hidden=hidden))
        except Exception as e: return Div(errstr(e), cls='lee-err')
    @rt('/files/panel')
    def files_panel_route(hidden: bool = False, open: str = ''):
        "Refresh only the file pane. `open` are the folders the client had expanded, drawn with it."
        return files_panel(ctx.fs, hidden, [p for p in open.split('\n') if p])
    @rt('/fs/events')
    async def fs_events(hidden: bool = False):
        "Changes on disk, pushed. Everything else in the tree is the client watching itself."
        from starlette.responses import StreamingResponse
        async def events():
            q = ctx.fs_watch.subscribe()   # a client that never iterates this never runs the finally
            try:
                while True:
                    paths, resync = await q.get()
                    _freshen(ctx, paths, resync)
                    shown, tracked = await off_loop(_sort_changes, ctx, paths, hidden)
                    stale_tree(tracked)
                    if shown or resync: yield sse('changed', {'paths': shown, 'resync': resync, 'git': bool(tracked)})
            finally: ctx.fs_watch.unsubscribe(q)
        return StreamingResponse(events(), media_type='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
    @rt('/fs/add-root')
    async def add_root_json(req):
        "Add a root without rebuilding the editor, model controls and every other pane."
        from ...core.projects import note_folder
        path = (await req.json()).get('path') or ''
        try:
            ctx.session.add_root(path); ctx.session.save(); note_folder(path)
            ctx.fs_watch.start(restart=True)
        except Exception as e: return fail(e)
        return {'ok': True}
    @rt('/fs/recent')
    def fs_recent():
        "Folders opened before: with nothing to launch on, this is the way back to a project."
        from ...core.projects import recent_folders
        open_now = {str(r) for r in ctx.fs.roots}
        return {'ok': True, 'home': str(Path.home()),
                'recent': [{'path': p, 'name': Path(p).name, 'open': p in open_now}
                           for p in recent_folders()]}
    @rt('/fs/paths')
    def fs_paths(path: str = ''):
        "Both ways of naming one file. Only the server knows which folder it is under."
        p = str(path or '').strip()
        if not p: return fail('no path')
        try: full = ctx.fs._check(p)
        except Exception as e: return fail(e)
        try: rel = str(Path(full).relative_to(ctx.fs.root_of(full)))
        except Exception: rel = ''
        return {'ok': True, 'absolute': str(full), 'relative': rel}
    @rt('/fs/forget-recent')
    async def fs_forget_recent(req):
        "Drop one folder from the welcome screen's list."
        from ...core.projects import forget_recent
        forget_recent((await req.json()).get('path') or '')
        return {'ok': True}
    @rt('/fs/browse')
    def fs_browse(path: str = ''):
        "Directories for the in-app folder picker. Files are intentionally never exposed here."
        try:
            p = Path(path or start_folder(ctx.session.project_root)).expanduser()
            partial = ''
            if not p.is_dir() and not str(path).endswith('/'): partial, p = p.name, p.parent
            p = p.resolve()
            if not p.is_dir(): raise NotADirectoryError(str(p))
            hidden = partial.startswith('.')
            dirs = sorted((x for x in p.iterdir() if x.is_dir() and (hidden or not x.name.startswith('.'))),
                key=lambda x: x.name.lower())
            parent = p.parent if p.parent != p else None
            return dict(path=str(p), parent=str(parent) if parent else '', partial=partial,
                dirs=[dict(name=x.name, path=str(x)) for x in dirs])
        except Exception as e: return fail(e)
    @rt('/fs/new')
    async def fs_new(req):
        "Create a file or folder directly inside `parent`. `kind` is 'file' or 'dir'; `name` is a bare filename."
        d = await req.json()
        parent, name, kind = d.get('parent') or '', d.get('name') or '', d.get('kind', 'file')
        try:
            target = ctx.fs.under(parent, name)
            e = ctx.fs.mkdir(target) if kind == 'dir' else ctx.session.create_document(target)
            if kind != 'dir': ctx.journal.record(f'Create {name}', [(e.path, None, Path(e.path).read_text())], kind='create')
            return {'ok': True, 'entry': e.dict()}
        except Exception as e: return fail(e)
    @rt('/fs/rename')
    async def fs_rename(req):
        d = await req.json()
        try:
            old = ctx.fs._check(d['path'], must_exist=True)
            entry = ctx.fs.rename(old, d['name'])
            # Where it went, not what was in it: a directory has no body and a binary does not
            # survive being one, and undoing a move needs neither.
            ctx.journal.record(f'Rename {old.name} to {entry.name}',
                               [], kind='rename', moved=[(entry.path, old)])
            moved = [ctx.session.retarget(tab, old, entry.path).path for tab in _forget(ctx, old)]
            return {'ok': True, 'entry': entry.dict(), 'retargeted': moved}
        except Exception as e: return fail(e)
    @rt('/fs/move')
    async def fs_move(req):
        "Move every selected path into one folder, as a single undoable operation."
        d = await req.json()
        dest, moved, failed = d.get('dest') or '', [], []
        for path in d.get('paths') or ([d['path']] if d.get('path') else []):
            try:
                old = ctx.fs._check(path, must_exist=True)
                entry = ctx.fs.move(old, dest)
                moved.append((entry.path, old))
                for tab in _forget(ctx, old): ctx.session.retarget(tab, old, entry.path)
            except Exception as e: failed.append({'path': str(path), 'error': errstr(e)})
        if moved:
            ctx.journal.record(f'Move {_batch(moved)} to {Path(dest).name}', [], kind='move',
                               moved=moved)
        return {'ok': not failed, 'moved': [str(new) for new, _ in moved], 'failed': failed}
    @rt('/fs/copy')
    async def fs_copy(req):
        "Copy every selected path into one folder. `duplicate` copies each beside itself instead."
        d = await req.json()
        paths = d.get('paths') or ([d['path']] if d.get('path') else [])
        made, failed = [], []
        for path in paths:
            try:
                src = ctx.fs._check(path, must_exist=True)
                into = src.parent if d.get('duplicate') else (d.get('dest') or '')
                entry = ctx.fs.copy(src, into, ctx.fs.free_name(src, into))
                made.append(entry.path)
            except Exception as e: failed.append({'path': str(path), 'error': errstr(e)})
        if made:
            label = f'Duplicate {_batch(made)}' if d.get('duplicate') else f'Copy {_batch(made)}'
            ctx.journal.record(label, [], kind='copy', created=made)
        return {'ok': not failed, 'created': [str(x) for x in made], 'failed': failed}
    @rt('/fs/remove-root')
    async def fs_remove_root(req):
        "Remove an open root from the workspace without touching anything on disk."
        from ...core.projects import drop_folder
        d = await req.json()
        try:
            ctx.session.drop_root(d['path'])
            ctx.session.save()
            # Out of the set that reopens, but still in `recent`: closing is not forgetting.
            drop_folder(d['path'])
            return {'ok': True}
        except Exception as e: return fail(e)
    @rt('/fs/delete')
    async def fs_delete(req):
        d = await req.json()
        try:
            p = ctx.fs._check(d['path'], must_exist=True)
            closed = _closed(ctx, p)
            # Aside, not gone: a folder used to leave no record at all and a binary came back as
            # replacement characters. The trash holds whichever it is, whole.
            key = ctx.fs.take(p, ctx.session.trash)
            ctx.journal.record(f'Delete {p.name}', [], kind='delete', trashed=[(p, key)])
            return {'ok': True, 'closed': closed}
        except Exception as e: return fail(e)
    def _serve_raw(path, download):
        "One file's bytes, for documents the browser renders itself. `inline` opens the viewer."
        from starlette.responses import FileResponse
        try:
            p = ctx.fs._check(path, must_exist=True)
            if not p.is_file(): return fail(f'{p.name} is not a file')
            kind = SERVED_TYPES.get(p.suffix.lower())
            if kind is None: return fail(f'{p.suffix or p.name} is not served as a raw document')
            disposition = 'attachment' if download else 'inline'
            return FileResponse(p, media_type=kind, headers={'Cache-Control': 'no-store',
                'X-Content-Type-Options': 'nosniff', 'Content-Disposition': f'{disposition}; filename="{p.name}"'})
        except Exception as e: return fail(e)
    @rt('/file/raw')
    def file_raw(path: str = '', download: bool = False): return _serve_raw(path, download)
    @rt('/file/raw/{name}')
    def file_raw_named(name: str, path: str = '', download: bool = False):
        "The same bytes, with the filename in the URL for the viewer's title. `name` is never resolved."
        return _serve_raw(path, download)
    _routes = app.router.routes
    _named = _routes.pop(next(i for i, r in enumerate(_routes) if getattr(r, 'path', '') == '/file/raw/{name}'))
    _static = next((i for i, r in enumerate(_routes) if '{ext:static}' in getattr(r, 'path', '')), len(_routes))
    _routes.insert(_static, _named)
    @rt('/fs/find')
    async def fs_find(req, q: str = '', limit: int = 200, scope: str = '', dirs: bool = False, more: bool = False):
        "Fuzzy match over the open folders, best match first; `more` searches only what the walk leaves out."
        root = ctx.session.project_root if scope == 'project' else None
        answer = lambda rows, partial=False: {'hits': rows, 'scope': str(root) if root else '', 'partial': partial}
        if not more: return answer(await off_loop(lambda: _ranked(q, ctx.fs.walk(root), root, limit, dirs)))
        name = q.strip().rsplit('/', 1)[-1]
        if not name: return answer([])
        got = await unless_gone(req, ctx.fs.hidden_files(r'(?i)' + r'.*'.join(map(re.escape, name)), root))
        if got is None: return answer([])
        return answer(await off_loop(_ranked, q, got[0], root, limit, dirs), got[1])
    def _ranked(q, files, root, limit, dirs):
        # Scored from the root's own name down, since letters in the absolute prefix matched every query.
        tops = [(os.path.join(str(r), ''), len(str(r.parent).rstrip('/')) + 1) for r in ctx.fs.roots]
        key = lambda p: (s := str(p))[max((n for t, n in tops if s.startswith(t)), default=0):]
        hits = fuzzy_rank(q, files, key=key, limit=limit)
        rows = [dict(path=str(p), name=p.name, lang=lang_for(p) or '', kind='file') for p in hits]
        if dirs:
            folders = {q for p in files for q in p.parents if root is None or q != root}
            found = fuzzy_rank(q, sorted(folders), key=key, limit=limit)
            rows = [dict(path=str(p), name=p.name + '/', lang='', kind='folder') for p in found] + rows
        return rows[:limit]
    def _on_disk(path):
        "What the file says now, or None when it is not there."
        try: return Path(path).read_text(encoding='utf-8', errors='replace')
        except OSError: return None
    def _forget_operation_buffers(op):
        for path in (r['path'] for r in op.get('resources', [])):
            ctx.docs.forget(path)
            if (tab := first(t for t in ctx.session.tabs if t.path == path)): tab.dirty = False
    @rt('/history/operations')
    def operation_history(limit: int = 50):
        return {'operations': ctx.journal.rows(limit)}
    @rt('/history/file')
    def file_history(path: str = '', limit: int = 60):
        "Every version Leela kept of one file, newest first. Undo is one step; this is all of them."
        target = str(path or (ctx.session.tab.path if ctx.session.tab else ''))
        if not target: return fail('name a file to read the history of')
        try: target = str(ctx.fs._check(target))
        except Exception as e: return fail(e, 400)
        return {'ok': True, 'path': target, 'versions': ctx.session.history.rows(target, limit),
                'disk_version': disk_version(target)}
    @rt('/history/files')
    def file_history_paths(limit: int = 200):
        "Which files have kept versions, most recently touched first."
        return {'ok': True, 'files': ctx.session.history.paths(limit)}
    @rt('/history/version')
    def file_history_version(id: str = ''):
        "One kept version, and how it differs from what is on disk now."
        row = ctx.session.history.row(str(id))
        if row is None: return fail(f'no such version {id}', 404)
        try: text = ctx.session.history.text(str(id))
        except Exception as e: return fail(e, 404)
        return {'ok': True, **row, 'text': text, **diff_payload(_on_disk(row['path']) or '', text, row['path'])}
    @rt('/history/restore')
    async def file_history_restore(req):
        "Put one kept version back. What it replaces is kept first, so a wrong restore is undoable."
        d = await req.json()
        row = ctx.session.history.row(str(d.get('id') or ''))
        if row is None: return fail(f"no such version {d.get('id')}", 404)
        try: text = ctx.session.history.text(row['id'])
        except Exception as e: return fail(e, 404)
        try:
            path = ctx.fs._check(row['path'])
            before = _on_disk(path)
            if before == text: return fail('that version is what the file already says', 409)
            ctx.fs.write(path, text)
        except Exception as e: return fail(e)
        ctx.docs.forget(str(path))
        if (tab := first(t for t in ctx.session.tabs if t.path == str(path))): tab.dirty = False
        name = Path(row['path']).name
        operation = ctx.journal.record(f'Restore {name} from local history',
                                      [(str(path), before, text)], kind='restore')
        return {'ok': True, 'path': str(path), 'version': row['id'],
                'operation_id': operation['id'] if operation else '',
                'disk_version': disk_version(str(path)), **diff_payload(before or '', text, path)}
    @rt('/history/undo')
    async def operation_undo(req):
        try:
            d = await req.json(); op = ctx.journal.undo(d.get('id', ''))
            _forget_operation_buffers(op)
            return {'ok': True, 'operation': op}
        except Exception as e: return fail(e, 409)
    @rt('/history/redo')
    async def operation_redo(req):
        try:
            d = await req.json(); op = ctx.journal.redo(d.get('id', ''))
            _forget_operation_buffers(op)
            return {'ok': True, 'operation': op}
        except Exception as e: return fail(e, 409)
