"Open documents: the tab strip, the buffers behind it, and disk agreement."

from __future__ import annotations

from fastcore.all import Path, first

from fasthtml.common import Div

from ... import errstr
from ...core.web import fail
from ..nb.nb import Notebook
from .ui import tab_bar

__all__ = ['CAPS', 'connect', 'disk_version']

CAPS = ('fs', 'history', 'pool', 'tab', 'docs')

def disk_version(path):
    "A cheap browser-watch token; changes whenever the active file is replaced or written."
    if not path: return ''
    try:
        s = Path(path).stat()
        return f'{s.st_mtime_ns}:{s.st_size}'
    except OSError: return 'missing'

def connect(app, ctx):
    rt = app.route
    session, docs = ctx.session, ctx.docs
    @rt('/tab/open')
    def tab_open(path: str):
        try:
            session.open(path)
            session.watch_env(None)
            session.save()
        except Exception as e: return Div(errstr(e), cls='lee-err')
        return tab_bar(session)
    @rt('/tab/select')
    def tab_select(i: int):
        session.activate(i)
        session.watch_env(None)
        return tab_bar(session)
    @rt('/tab/close')
    async def tab_close(i: int):
        key = session.kernel_key(session.tabs[i]) if 0 <= i < len(session.tabs) else None
        session.close(i); session.watch_env(None); session.save()
        # A private key names one tab, a folder key names several. Both go when the last of them does.
        if key and not any(session.kernel_key(t) == key for t in session.tabs): await ctx.pool.close(key)
        return tab_bar(session)
    @rt('/tab/move')
    def tab_move(i: int, j: int):
        "Reorder by drag. The strip is the user's ordering of their own work, so it persists."
        session.move_tab(i, j); session.save()
        return tab_bar(session)
    @rt('/tab/new')
    def tab_new(kind: str = 'notebook'):
        session.new_scratch(kind)
        session.watch_env(None)
        return tab_bar(session)
    def _held(t):
        "The version the cached copy of `t` was read at, and whether the file has moved since."
        key, now = t.path or t.title, disk_version(t.path) if t.path else ''
        was = docs.versions.get(key)
        return (now, False) if was is None or was == now else (was, True)

    @rt('/tab/state')
    def tab_state(path: str = ''):
        "Everything needed to mount the active tab, or an open tab addressed by absolute path."
        want = str(Path(path).expanduser().resolve()) if path else ''
        t = first(session.tabs, lambda x: x.path == want) if path else ctx.tab
        if t is None: return {'kind': None}
        held, stale = _held(t)
        if t.kind == 'notebook':
            key = t.path or t.title
            try:
                nb = docs.docs.get(key)
                if nb is None:
                    nb = Notebook.load(t.path) if t.path else Notebook.blank()
                    docs.versions[key] = held
            except Exception as e: return {'kind': 'error', 'error': errstr(e)}
            docs.docs[key] = nb
            return {'kind': 'notebook', 'path': t.path, 'title': t.title, 'dirty': t.dirty,
                    'disk_version': held, 'stale': stale, 'cells': [c.dict() for c in nb.cells]}
        if t.kind in ('pdf', 'image'):
            return {'kind': t.kind, 'path': t.path, 'title': t.title,
                    'disk_version': disk_version(t.path)}
        if t.kind == 'vault':
            vault, shelf, doc = (t.ref.split('|') + ['', '', ''])[:3]
            return {'kind': 'vault', 'title': t.title, 'vault': vault, 'shelf': shelf, 'doc': doc}
        if t.kind == 'vaultwb':
            # A place rather than a document: the client asks `/vault/workbench` for the markup.
            return {'kind': 'vaultwb', 'title': t.title, 'view': t.ref or 'browse'}
        if t.kind == 'web':
            # Same shape again: the page lives in Chrome, and the panel opens `/browser/ws`.
            return {'kind': 'web', 'title': t.title, 'target': t.ref}
        try:
            key = t.path or t.title
            if key in docs.buffers: text = docs.buffers[key]
            else:
                text = ctx.fs.read(t.path) if t.path else ''
                docs.versions[key] = held
        except Exception as e: return {'kind': 'error', 'error': errstr(e)}
        return {'kind': 'text', 'path': t.path, 'title': t.title, 'lang': t.lang or '',
                'disk_version': held, 'stale': stale, 'text': text}
    @rt('/tab/disk')
    def tab_disk(path: str = ''):
        "Current on-disk text for the explicit conflict/merge editor."
        try:
            p = ctx.fs._check(path or (ctx.tab.path if ctx.tab else ''), must_exist=True)
            if p.suffix == '.ipynb':
                return {'path': str(p), 'kind': 'notebook',
                        'cells': [c.dict() for c in Notebook.load(p).cells],
                        'disk_version': disk_version(p)}
            return {'path': str(p), 'kind': 'text', 'text': ctx.fs.read(p),
                    'disk_version': disk_version(p)}
        except Exception as e: return fail(e)
    outside = {}
    def keep_outside_write(path, version):
        """A write Leela did not make, kept before the editor takes it.

        This poll is the only place another process's edit to an open file is noticed, and the
        editor's next move is to load it over what is there."""
        if outside.get(path) == version: return
        outside[path] = version
        try: ctx.history.keep(path, None, ctx.fs.read(path), 'changed outside Leela')
        except Exception: pass
    @rt('/tab/watch')
    def tab_watch():
        "Pollable disk identity for the open document; no file contents cross the wire."
        t = ctx.tab
        held = disk_version(t.path) if t else ''
        if t is not None and t.path and held not in ('', 'missing'):
            known = docs.versions.get(docs.key(t))
            if known and known != held: keep_outside_write(t.path, held)
        return {'path': t.path if t else '', 'disk_version': held}
    @rt('/tab/reload')
    async def tab_reload(req):
        "Drop server-side editor caches so the next state read comes straight from disk."
        d = await req.json()
        t = ctx.tab
        if t is None or (d.get('path') and d.get('path') != t.path): return fail('that tab is no longer active')
        docs.forget(t.path or t.title)
        t.dirty = False
        return {'ok': True, 'path': t.path}
    @rt('/tab/buffer')
    async def tab_buffer(req):
        "Persist an editor buffer in memory so a tab switch cannot discard unsaved typing."
        d = await req.json()
        path, kind, text = d.get('path') or d.get('title') or '', d.get('kind'), d.get('text', '')
        tab = first(session.tabs, lambda t: docs.key(t) == path)
        if tab is None: return fail('that tab is no longer open')
        docs.bases.setdefault(path, str(d.get('base_disk_version') or disk_version(tab.path)))
        docs.versions.setdefault(path, docs.bases[path])   # a draft descends from what was read
        if kind == 'notebook':
            nb = docs.docs.get(path)
            i = int(d.get('i', -1))
            if nb is not None and 0 <= i < len(nb) and (not d.get('id') or nb[i].id == d.get('id')):
                nb[i].source = text; nb.dirty = True
        else: docs.buffers[path] = text
        tab.dirty = True
        return {'ok': True}
