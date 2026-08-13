"""Code search: literal, semantic, and the call graph.

Every reply carries the backend that produced it, so an empty result is never a mystery --
`ripgrep found nothing` and `the index is not built` look identical otherwise, and only one
of them is worth acting on.

Everything here goes through `off_loop`. The backends are blocking: ripgrep is a
subprocess, FTS is SQLite, and ANN search is usearch over an mmap'd index. Running any of
them on the event loop would stall every other request in the workspace, including the
streaming ones.

`ctx.search` is a `SearchPort` (`leela/core/ports.py`) -- this block never names the
concrete `Search` class, which is what lets an alternate implementation be substituted
under it.
"""

from __future__ import annotations

from ...core.web import fail, found, off_loop

__all__ = ['CAPS', 'connect']

CAPS = ('search', 'fs')

# The browser's default is `rg`; FTS and ANN activate only when a person picks them. The
# agent's natural-language query is a different contract and goes through `agent_search`.
MODES = ('context', 'repo', 'env', 'all', 'rg', 'symbols', 'fts', 'ann')

# *Where* to search, which is a different question from which backend answers -- hence a separate
# parameter rather than another mode. `mode='repo'` already means Kosha's repo index as opposed to
# its package index, and overloading that word would have made two unrelated things one.
SCOPES = ('project', 'workspace')


def connect(app, ctx):
    rt = app.route

    @rt('/search')
    async def search_route(q: str = '', regex: bool = False, limit: int = 60, mode: str = 'rg',
                           exts: str = '', scope: str = 'project'):
        """Ripgrep by default; every blocking search backend runs off the web event loop.

        `scope` is a word, not a path. The browser says *which* scope it means and this resolves
        it from the session -- a root arriving as a parameter would be a way to point the search
        at somewhere the sandbox never listed, and "it is only a search" is how that becomes a way
        to read files.

        `project` is the default because a workspace holds several checkouts and a search of all
        of them answers a question nobody asked: matches from the repository you are not working
        in, ranked among the ones you are. `workspace` is still there for when you do mean both.
        """
        if mode not in MODES: return fail(f'unknown search mode {mode!r}')
        if scope not in SCOPES: return fail(f'unknown search scope {scope!r}')
        roots = None
        if scope == 'project':
            root = ctx.session.project_root
            roots = [root] if root is not None else None
        hits = await off_loop(ctx.search.search, q, limit=limit, regex=regex, mode=mode,
                              exts=exts, roots=roots)
        return found(ctx.search, hits) | {
            'scope': scope, 'exts': exts,
            'searched': [str(r) for r in (roots if roots is not None else ctx.fs.roots)]}

    @rt('/code/status')
    async def code_status():
        return await off_loop(ctx.search.status)

    @rt('/code/package-api')
    async def code_package_api(package: str = ''):
        rows = await off_loop(ctx.search.package_api, package)
        return {'package': package, 'note': ctx.search.note, 'symbols': rows}

    @rt('/outline')
    async def outline_route(path: str):
        return {'symbols': [h.dict() for h in await off_loop(ctx.search.symbols, path)]}

    @rt('/code/definition')
    async def code_definition(name: str = '', path: str = '', limit: int = 30):
        return found(ctx.search, await off_loop(ctx.search.definitions, name, path, limit))

    @rt('/code/usages')
    async def code_usages(name: str = '', limit: int = 200):
        return found(ctx.search, await off_loop(ctx.search.usages, name, limit))

    @rt('/code/sync')
    async def code_sync():
        try: return await ctx.search.async_sync(True, True)
        except Exception as e: return fail(e)

    @rt('/similar')
    async def similar_route(path: str, line: int = 1, mode: str = 'cluster', limit: int = 25):
        """Code like the function at `path:line`.

        `mode=cluster` answers "the family this belongs to" via usearch clustering;
        `mode=knn` answers "the N closest things". The first is usually what you want
        when hunting for every place a pattern was already implemented.
        """
        fn = ctx.search.peers if mode == 'cluster' else ctx.search.similar
        return found(ctx.search, await off_loop(fn, path, line, limit=limit))

    @rt('/clusters')
    async def clusters_route(limit: int = 40):
        "An ANN clustering of the whole indexed corpus -- a map of the codebase by shape."
        cs = await off_loop(ctx.search.clusters)
        return {'note': ctx.search.note, 'clusters': [c.dict() for c in cs[:limit]]}
