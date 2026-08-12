"""The open folders, the working directory, and the other windows.

`/workspace/info` reports two different things that are easy to confuse. `roots` are the
folders open in *this* workspace; `workspaces` are the independently hosted sibling
windows, each with its own `Workspace`, kernels and agent, reached at
`<slug>.localhost`. See `docs/multi-workspace-architecture.md`.

The working directory is per tab, with automatic discovery as the default: a script runs
from its containing Git repository root unless someone pinned a directory with the `cwd`
pill. `explicit` is what the pill uses to show which of the two is in force -- without it
the browser cannot tell a pinned directory from a discovered one that happens to match.
"""

from __future__ import annotations

from ...core.web import fail

__all__ = ['CAPS', 'connect']

CAPS = ('fs', 'tab', 'catalog')


def connect(app, ctx):
    rt = app.route

    @rt('/workspace/activate')
    async def workspace_activate(req):
        """Point the project surfaces -- source control, releases, deploys -- at one folder.

        A workspace holds several checkouts. Choosing one here is the answer to "which
        project", and it is remembered: `roots[0]` was standing in for that answer, so adding
        a second folder and switching to it left the branch pill on the first one.
        """
        d = await req.json()
        try:
            root = ctx.session.activate_root(d.get('path') or '')
            ctx.session.save()
            return {'ok': True, 'active': str(root)}
        except Exception as e: return fail(e)

    @rt('/workspace/info')
    def workspace_info():
        "The current multi-root project plus independently hosted workspace windows."
        tab, fs = ctx.tab, ctx.fs
        active = ctx.session.project_root
        catalog = ctx.catalog
        sites = catalog() if callable(catalog) else list(catalog or ())
        return {'active': str(active or ''),
                'roots': [{'path': str(root), 'name': root.name} for root in fs.roots],
                'workspaces': sites}

    @rt('/cwd')
    def cwd_info():
        t, fs = ctx.tab, ctx.fs
        return {'cwd': str(ctx.session.cwd_for() or ''), 'explicit': bool(t and t.cwd),
                'root': str(fs.root_of(t.path) if t and t.path else (ctx.session.project_root or ''))}

    @rt('/cwd/set')
    async def cwd_set(req):
        d = await req.json()
        try:
            p = ctx.session.set_cwd(d.get('path'))
            ctx.session.save()
            return {'ok': True, 'cwd': str(p), 'explicit': bool(ctx.tab and ctx.tab.cwd)}
        except Exception as e: return fail(e)
