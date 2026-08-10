"""Open documents: the tab strip, the buffers behind it, and disk agreement.

Tab routes swap only `#tabbar`, never the whole shell. Re-rendering everything for a tab
switch would collapse the file tree, drop the exec editor and reset the variable panel, so
the client re-mounts just the editor when `#tabbar` changes.

Three things guard against showing a document that is not what is on disk:

- `/tab/state` prefers the **in-memory** notebook over the file. The document owns unsaved
  outputs and running state, and reloading from disk on every tab switch erased both while
  work was still in flight.
- `/tab/reload` is the deliberate opposite, and exists because agent edits happen outside
  the open document objects. Without it a browser remount would faithfully redisplay a
  stale notebook the server had cached.
- `disk_version` is a cheap watch token (`mtime:size`) so `/tab/watch` can be polled
  without any file contents crossing the wire.

`watch_env(None)` on every tab change is not incidental. A manually watched app belongs to
the tab it was chosen from; switching tabs has to restore the new tab's own runtime rather
than leave the variable panel pointed somewhere unrelated.
"""

from __future__ import annotations

from pathlib import Path

from fasthtml.common import Div

from ... import errstr
from ...core.web import fail
from ..nb.nb import Notebook
from .ui import tab_bar

__all__ = ['CAPS', 'connect', 'disk_version']

CAPS = ('fs', 'pool', 'tab', 'docs')


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
            # Notebook tabs own kernels by default. A manually watched app belongs to the
            # tab it was chosen from; changing tabs restores the new tab's own runtime.
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
        private = bool(0 <= i < len(session.tabs) and session.tabs[i].private_kernel)
        session.close(i); session.watch_env(None); session.save()
        if private and key: await ctx.pool.close(key)
        return tab_bar(session)

    @rt('/tab/new')
    def tab_new(kind: str = 'notebook'):
        session.new_scratch(kind)
        session.watch_env(None)
        return tab_bar(session)

    @rt('/tab/state')
    def tab_state(path: str = ''):
        "Everything needed to mount the active tab, or an open tab addressed by absolute path."
        t = next((x for x in session.tabs if x.path == str(Path(path).expanduser().resolve())), None) if path else ctx.tab
        if t is None: return {'kind': None}
        if t.kind == 'notebook':
            key = t.path or t.title
            try:
                # The in-memory document owns unsaved outputs and running state. Reloading
                # from disk on every tab switch erased both while work was still in flight.
                nb = docs.docs.get(key)
                if nb is None: nb = Notebook.load(t.path) if t.path else Notebook.blank()
            except Exception as e: return {'kind': 'error', 'error': errstr(e)}
            docs.docs[key] = nb
            return {'kind': 'notebook', 'path': t.path, 'title': t.title, 'dirty': t.dirty,
                    'disk_version': disk_version(t.path), 'cells': [c.dict() for c in nb.cells]}
        try:
            key = t.path or t.title
            # `in` rather than `.get(...) or`: a buffer holding the empty string is a real
            # answer (you deleted everything and have not saved), not a miss to fall
            # through to disk for.
            text = docs.buffers[key] if key in docs.buffers else (ctx.fs.read(t.path) if t.path else '')
        except Exception as e: return {'kind': 'error', 'error': errstr(e)}
        return {'kind': 'text', 'path': t.path, 'title': t.title, 'lang': t.lang or '',
                'disk_version': disk_version(t.path), 'text': text}

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

    @rt('/tab/watch')
    def tab_watch():
        "Pollable disk identity for the open document; no file contents cross the wire."
        t = ctx.tab
        return {'path': t.path if t else '', 'disk_version': disk_version(t.path) if t else ''}

    @rt('/tab/reload')
    async def tab_reload(req):
        """Drop server-side editor caches so the next state read comes straight from disk.

        Agent edits happen outside the open document objects. Without this invalidation a
        browser remount could faithfully redisplay the stale notebook it had cached.
        """
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
        tab = next((t for t in session.tabs if docs.key(t) == path), None)
        if tab is None: return fail('that tab is no longer open')
        docs.bases.setdefault(path, str(d.get('base_disk_version') or disk_version(tab.path)))
        if kind == 'notebook':
            nb = docs.docs.get(path)
            i = int(d.get('i', -1))
            if nb is not None and 0 <= i < len(nb) and (not d.get('id') or nb[i].id == d.get('id')):
                nb[i].source = text; nb.dirty = True
        else: docs.buffers[path] = text
        tab.dirty = True
        return {'ok': True}
