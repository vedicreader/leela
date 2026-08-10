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
from ...fs import lang_for
from .ui import files_panel, git_tree_state, tree_node

__all__ = ['CAPS', 'connect']

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
            p = Path(path or Path.home()).expanduser().resolve()
            if not p.is_dir(): raise NotADirectoryError(str(p))
            dirs = sorted((x for x in p.iterdir() if x.is_dir() and not x.name.startswith('.')),
                          key=lambda x: x.name.lower())
            parent = p.parent if p.parent != p else None
            return {'path': str(p), 'parent': str(parent) if parent else '',
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

    @rt('/fs/find')
    def fs_find(q: str = '', limit: int = 200):
        "Quick-open: fuzzy match over every file in the open folders, best match first."
        hits = fuzzy_rank(q, ctx.fs.walk(), key=str, limit=limit)
        return {'hits': [{'path': str(p), 'name': p.name, 'lang': lang_for(p) or ''} for p in hits]}
