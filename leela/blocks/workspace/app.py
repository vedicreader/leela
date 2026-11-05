"The open folders, the working directory, and the other windows."

from __future__ import annotations

from fastcore.all import Path
from ...core.web import fail

__all__ = ['CAPS', 'connect']

CAPS = ('fs', 'tab', 'catalog')

def connect(app, ctx):
    rt = app.route
    @rt('/workspace/activate')
    async def workspace_activate(req):
        "Point the project surfaces (source control, releases, deploys) at one folder."
        d = await req.json()
        try:
            root = ctx.session.activate_root(d.get('path') or '')
            ctx.session.save()
            return {'ok': True, 'active': str(root)}
        except Exception as e: return fail(e)
    @rt('/workspace/info')
    def workspace_info():
        "The current multi-root project plus independently hosted workspace windows."
        catalog = ctx.catalog
        sites = catalog() if callable(catalog) else list(catalog or ())
        return {'active': str(ctx.session.project_root or ''),
                'roots': [{'path': str(root), 'name': root.name} for root in ctx.fs.roots],
                'workspaces': sites}
    @rt('/cwd')
    def cwd_info():
        t, fs = ctx.tab, ctx.fs
        root = fs.root_of(t.path) if t and t.path and fs.covers(Path(t.path).resolve()) else ctx.session.project_root
        return {'cwd': str(ctx.session.cwd_for() or ''), 'explicit': bool(t and t.cwd), 'root': str(root or '')}
    @rt('/cwd/set')
    async def cwd_set(req):
        d = await req.json()
        try:
            p = ctx.session.set_cwd(d.get('path'))
            ctx.session.save()
            return {'ok': True, 'cwd': str(p), 'explicit': bool(ctx.tab and ctx.tab.cwd)}
        except Exception as e: return fail(e)
