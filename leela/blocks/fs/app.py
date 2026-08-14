"""Files: the tree, the folder picker, and the four mutations.

Every file write is journalled with its before and after text, so `/history/undo` can reverse
it; directories are not, having no text to restore. `/fs/browse` is the one route that steps
outside the sandbox, because a folder picker has to show folders that are not open yet -- it
exposes directories only. Everything else resolves through `ctx.fs._check`.
"""

from __future__ import annotations

from fastcore.all import Path

from fasthtml.common import Div

from ... import errstr
from ...core.web import fail
from ...core.diffs import fuzzy_rank
from .fs import lang_for
from .ui import files_panel, git_tree_state, tree_node

__all__ = ['CAPS', 'connect', 'SERVED_TYPES']

# An allowlist, not `mimetypes.guess_type`: these bytes go to a renderer, so what counts as
# renderable is a decision. With `nosniff` a mislabelled file cannot be reinterpreted.
SERVED_TYPES = {'.pdf': 'application/pdf', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.gif': 'image/gif', '.webp': 'image/webp', '.svg': 'image/svg+xml', '.ico': 'image/x-icon',
    '.bmp': 'image/bmp'}

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
        from ...core.projects import note_folder
        path = (await req.json()).get('path') or ''
        try: ctx.session.add_root(path); ctx.session.save(); note_folder(path)
        except Exception as e: return fail(e)
        return {'ok': True}

    @rt('/fs/recent')
    def fs_recent():
        "Folders opened before: with no argument to launch on, this is the way back to a project."
        from ...core.projects import recent_folders
        open_now = {str(r) for r in ctx.fs.roots}
        return {'ok': True, 'home': str(Path.home()),
                'recent': [{'path': p, 'name': Path(p).name, 'open': p in open_now}
                           for p in recent_folders()]}

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
            p = Path(path or Path.home()).expanduser()
            # A half-typed path browses the part that exists and returns the rest as `partial`.
            partial = ''
            if not p.is_dir() and not str(path).endswith('/'): partial, p = p.name, p.parent
            p = p.resolve()
            if not p.is_dir(): raise NotADirectoryError(str(p))
            hidden = partial.startswith('.')   # `.venv` appears only once someone types a dot
            dirs = sorted((x for x in p.iterdir() if x.is_dir() and (hidden or not x.name.startswith('.'))),
                key=lambda x: x.name.lower())
            parent = p.parent if p.parent != p else None
            return dict(path=str(p), parent=str(parent) if parent else '', partial=partial,
                dirs=[dict(name=x.name, path=str(x)) for x in dirs])
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
            if kind != 'dir': ctx.journal.record(f'Create {name}', [(e.path, None, Path(e.path).read_text())], kind='create')
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
            before = p.read_text(encoding='utf-8', errors='replace') if p.is_file() else None
            ctx.fs.delete(p)
            if before is not None: ctx.journal.record(f'Delete {p.name}', [(p, before, None)], kind='delete')
            if (i := ctx.session.find(d['path'])) is not None: ctx.session.close(i)
            return {'ok': True}
        except Exception as e: return fail(e)

    def _serve_raw(path, download):
        "One file's bytes, for documents the browser renders itself. `inline` opens the viewer; `nosniff` pins the type."
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
        "The same bytes, with the filename in the URL for the viewer's title. `name` is never resolved against disk."
        return _serve_raw(path, download)

    # Order matters: FastHTML's static catch-all `/{fname:path}.{ext:static}` is registered ahead of
    # every block and would answer `/file/raw/paper.pdf` itself, so this route must precede it.
    _routes = app.router.routes
    _named = _routes.pop(next(i for i, r in enumerate(_routes) if getattr(r, 'path', '') == '/file/raw/{name}'))
    _static = next((i for i, r in enumerate(_routes) if '{ext:static}' in getattr(r, 'path', '')), len(_routes))
    _routes.insert(_static, _named)

    @rt('/fs/find')
    def fs_find(q: str = '', limit: int = 200, scope: str = '', dirs: bool = False):
        """Fuzzy match over the open folders, best match first.

        `scope='project'` narrows to the chosen folder, which is what the agent's `@` means: in a
        workspace with several checkouts open, every file everywhere is not a useful list of what
        this project contains. Quick-open keeps the default, because opening a file across the
        workspace is exactly its job.
        """
        root = ctx.session.project_root if scope == 'project' else None
        files = ctx.fs.walk(root)
        hits = fuzzy_rank(q, files, key=str, limit=limit)
        rows = [dict(path=str(p), name=p.name, lang=lang_for(p) or '', kind='file') for p in hits]
        if dirs:
            # Derived from the files rather than walked separately, so the folder list inherits
            # `walk`'s skips: nobody wants `.git` or `node_modules` offered as somewhere to look.
            folders = {q for p in files for q in p.parents if root is None or q != root}
            found = fuzzy_rank(q, sorted(folders), key=str, limit=limit)
            rows = [dict(path=str(p), name=p.name + '/', lang='', kind='folder') for p in found] + rows
        return {'hits': rows[:limit], 'scope': str(root) if root else ''}
