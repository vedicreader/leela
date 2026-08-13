"""Files: the tree, the folder picker, and the four mutations.

Every write is journalled with its before and after text, which is what makes
`/history/undo` able to reverse a rename or an accidental delete. Directories are not
journalled — a `mkdir` has no text to restore, and reversing a recursive delete is not
something a text journal can honestly promise.

`/fs/browse` is the one route here that deliberately steps outside the sandbox: it powers
the in-app folder picker, which by definition has to show folders that are not open yet.
It exposes *directories only*, never files, so it cannot be used to read anything — and
adding a root still goes through `Workspace.add_root`.

Everything else resolves through `ctx.fs`, whose `_check` collapses `..` and follows
symlinks before refusing anything that lands outside an open root.
"""

from __future__ import annotations

from pathlib import Path

from fasthtml.common import Div

from ... import errstr
from ...core.web import fail
from ...core.diffs import fuzzy_rank
from .fs import lang_for
from .ui import files_panel, git_tree_state, tree_node

__all__ = ['CAPS', 'connect', 'SERVED_TYPES']

# What `/file/raw` will hand over, and as what. An allowlist rather than `mimetypes.guess_type`:
# this route returns bytes the browser is about to *render*, so the set of things it will claim
# are renderable is a decision, not a lookup. `nosniff` plus a fixed type is what keeps a
# mislabelled file from being interpreted as something it is not.
SERVED_TYPES = {'.pdf': 'application/pdf', '.png': 'image/png', '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.webp': 'image/webp',
                '.svg': 'image/svg+xml', '.ico': 'image/x-icon'}

CAPS = ('fs', 'journal')


def connect(app, ctx):
    rt = app.route

    @rt('/tree')
    def tree(path: str):
        try:
            state = git_tree_state(ctx.fs)
            return tuple(tree_node(e, state) for e in ctx.fs.ls(path))
        except Exception as e: return Div(errstr(e), cls='lee-err')

    @rt('/files/panel')
    def files_panel_route():
        "Refresh only the file pane; the client restores expansion, selection and scroll."
        return files_panel(ctx.fs)

    @rt('/fs/add-root')
    async def add_root_json(req):
        "Add a root without rebuilding the editor, model controls and every other pane."
        d = await req.json()
        try: ctx.session.add_root(d.get('path') or ''); ctx.session.save()
        except Exception as e: return fail(e)
        return {'ok': True}

    @rt('/fs/browse')
    def fs_browse(path: str = ''):
        "Directories for the in-app folder picker. Files are intentionally never exposed here."
        try:
            p = Path(path or Path.home()).expanduser()
            # A half-typed path is the normal state of a box someone is completing in, so the
            # part that exists is browsed and the rest is handed back as `partial` rather than
            # the whole thing being refused for naming a folder that is not there yet.
            partial = ''
            if not p.is_dir() and not str(path).endswith('/'): partial, p = p.name, p.parent
            p = p.resolve()
            if not p.is_dir(): raise NotADirectoryError(str(p))
            # Hidden folders stay out of the way until they are asked for by name: nobody
            # scrolling a list wants `.cache`, and everybody typing `.ven` wants `.venv`.
            hidden = partial.startswith('.')
            dirs = sorted((x for x in p.iterdir() if x.is_dir() and (hidden or not x.name.startswith('.'))),
                          key=lambda x: x.name.lower())
            parent = p.parent if p.parent != p else None
            return {'path': str(p), 'parent': str(parent) if parent else '', 'partial': partial,
                    'dirs': [{'name': x.name, 'path': str(x)} for x in dirs]}
        except Exception as e: return fail(e)

    @rt('/fs/new')
    async def fs_new(req):
        "Create a file or folder. `kind` is 'file' or 'dir'."
        d = await req.json()
        parent, name, kind = d.get('parent') or '', d.get('name') or '', d.get('kind', 'file')
        if not name: return fail('name required')
        try:
            target = Path(parent)/name
            e = ctx.fs.mkdir(target) if kind == 'dir' else ctx.session.create_document(target)
            if kind != 'dir':
                ctx.journal.record(f'Create {name}', [(e.path, None, Path(e.path).read_text())],
                                   kind='create')
            return {'ok': True, 'entry': e.dict()}
        except Exception as e: return fail(e)

    @rt('/fs/rename')
    async def fs_rename(req):
        d = await req.json()
        try:
            old = ctx.fs._check(d['path'], must_exist=True)
            before = old.read_text(encoding='utf-8', errors='replace') if old.is_file() else None
            entry = ctx.fs.rename(old, d['name'])
            if before is not None:
                ctx.journal.record(f'Rename {old.name} to {entry.name}',
                                   [(old, before, None), (entry.path, None, before)], kind='rename')
            return {'ok': True, 'entry': entry.dict()}
        except Exception as e: return fail(e)

    @rt('/fs/remove-root')
    async def fs_remove_root(req):
        "Remove an open root from the workspace without touching anything on disk."
        d = await req.json()
        try:
            ctx.session.drop_root(d['path']); ctx.session.save()
            return {'ok': True}
        except Exception as e: return fail(e)

    @rt('/fs/delete')
    async def fs_delete(req):
        d = await req.json()
        try:
            p = ctx.fs._check(d['path'], must_exist=True)
            before = p.read_text(encoding='utf-8', errors='replace') if p.is_file() else None
            ctx.fs.delete(p)
            if before is not None:
                ctx.journal.record(f'Delete {p.name}', [(p, before, None)], kind='delete')
            if (i := ctx.session.find(d['path'])) is not None: ctx.session.close(i)
            return {'ok': True}
        except Exception as e: return fail(e)

    @rt('/file/raw')
    def file_raw(path: str = '', download: bool = False):
        """One file's bytes, for the documents the browser renders better than we could.

        A PDF is the case this exists for: Chrome and Safari ship a viewer, and the honest thing
        in a browser-based IDE is to hand the file over rather than reimplement one badly. So the
        response is the file, and the `<iframe>` in the tab is the whole feature.

        `ctx.fs._check` is the boundary, exactly as for every other path from the browser. Two
        headers beyond the type matter: `Content-Disposition: inline` so the viewer opens it
        instead of the browser downloading it, and `X-Content-Type-Options: nosniff` so a file
        whose suffix lies cannot be re-interpreted as something executable.
        """
        from starlette.responses import FileResponse
        try:
            p = ctx.fs._check(path, must_exist=True)
            if not p.is_file(): return fail(f'{p.name} is not a file')
            kind = SERVED_TYPES.get(p.suffix.lower())
            if kind is None: return fail(f'{p.suffix or p.name} is not served as a raw document')
            disposition = 'attachment' if download else 'inline'
            return FileResponse(p, media_type=kind, headers={
                'Content-Disposition': f'{disposition}; filename="{p.name}"',
                'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store'})
        except Exception as e: return fail(e)

    @rt('/fs/find')
    def fs_find(q: str = '', limit: int = 200):
        "Quick-open: fuzzy match over every file in the open folders, best match first."
        hits = fuzzy_rank(q, ctx.fs.walk(), key=str, limit=limit)
        return {'hits': [{'path': str(p), 'name': p.name, 'lang': lang_for(p) or ''} for p in hits]}
