"Search routes over the `SearchPort`; every backend blocks, so every call goes through."

from __future__ import annotations

import asyncio

from ...core.web import fail, found, off_loop
from .search import SETTING_WEIGHTS, Weights
from .signals import Signals, search_vault_path

__all__ = ['CAPS', 'connect']

CAPS = ('fs', 'search', 'vaults')

MODES = ('context', 'repo', 'env', 'all', 'rg', 'symbols', 'fts', 'ann')

SCOPES = ('project', 'workspace')

def connect(app, ctx):
    rt = app.route
    signals = Signals()
    def prefs():
        "The effective `search` settings: the ranking weights and what may be remembered."
        from ..settings.settings import Settings
        try: return Settings(ctx.session.project_root).effective().get('search') or {}
        except Exception: return {}
    def weigh(values=None):
        "Rank with the weights settings currently hold. Read per request, so a change is live."
        ctx.search.weights = Weights.load(values if values is not None else prefs())
        return ctx.search.weights
    async def remember(session):
        "One document per search session, in a vault of its own the vault surfaces can then read."
        if not await off_loop(signals.remember, session): return None
        try: return ctx.vaults.attach(search_vault_path(), name='search')
        except Exception: return None
    def scope_roots(scope):
        "The folders a scope names: the active project's, or `None` for the whole workspace."
        if scope != 'project': return None
        root = ctx.session.project_root
        return [root] if root is not None else None
    def searched(roots):
        "The folders actually searched, for the client to say where the answer came from."
        return [str(r) for r in (roots if roots is not None else ctx.fs.roots)]
    @rt('/search')
    async def search_route(q: str = '', regex: bool = False, limit: int = 60, mode: str = 'rg',
        exts: str = '', scope: str = 'project'):
        "Ripgrep by default, scoped to `project` since a workspace holds several checkouts."
        if mode not in MODES: return fail(f'unknown search mode {mode!r}')
        if scope not in SCOPES: return fail(f'unknown search scope {scope!r}')
        roots = scope_roots(scope)
        w = weigh()
        hits = await off_loop(ctx.search.search, q, limit=limit, regex=regex, mode=mode,
            exts=exts, roots=roots)
        return found(ctx.search, hits) | {
            'scope': scope, 'exts': exts, 'searched': searched(roots), 'weights': w.settings()}
    @rt('/search/stream')
    async def search_stream(req, q: str = '', regex: bool = False, limit: int = 60,
        exts: str = '', scope: str = 'project'):
        "`all`, but each backend reports the moment it finishes, so the list fills from the fastest."
        from starlette.responses import StreamingResponse
        from ...core.web import sse
        if scope not in SCOPES: return fail(f'unknown search scope {scope!r}')
        roots = scope_roots(scope)
        per = max(12, min(limit, 40))
        w = weigh()
        async def events():
            yield sse('start', {'legs': list(ctx.search.ALL_LEGS), 'scope': scope,
                'searched': searched(roots), 'weights': w.settings()})
            if not (q or '').strip():
                yield sse('done', {'note': 'nothing to search for'})
                return
            async def run(name):
                hits, note = await off_loop(ctx.search.leg, name, q, per, regex, exts, roots)
                return name, hits, note
            tasks = [asyncio.ensure_future(run(name)) for name in ctx.search.ALL_LEGS]
            try:
                for done in asyncio.as_completed(tasks):
                    if await req.is_disconnected(): break
                    name, hits, note = await done
                    yield sse('leg', {'leg': name, 'note': note,
                        'hits': [h.dict() for h in hits]})
            finally:
                for t in tasks:
                    if not t.done(): t.cancel()
            yield sse('done', {'note': 'every backend reported'})
        return StreamingResponse(events(), media_type='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
    @rt('/code/status')
    async def code_status(): return await off_loop(ctx.search.status)
    @rt('/code/package-api')
    async def code_package_api(package: str = ''):
        rows = await off_loop(ctx.search.package_api, package)
        return {'package': package, 'note': ctx.search.note, 'symbols': rows}
    @rt('/outline')
    async def outline_route(path: str): return {'symbols': [h.dict() for h in await off_loop(ctx.search.symbols, path)]}
    @rt('/code/definition')
    async def code_definition(name: str = '', path: str = '', limit: int = 30):
        return found(ctx.search, await off_loop(ctx.search.definitions, name, path, limit))
    @rt('/code/usages')
    async def code_usages(name: str = '', limit: int = 200): return found(ctx.search, await off_loop(ctx.search.usages, name, limit))
    @rt('/code/jump')
    async def code_jump(name: str = '', path: str = '', line: int = 0, cell_index: int = -1,
                        limit: int = 30, dotted: str = ''):
        "One key both ways: the declaration of a usage, the usages of a declaration."
        kind, hits = await off_loop(ctx.search.declaration_or_usages, name, path, line, cell_index,
                                    limit, dotted)
        return {'kind': kind, **found(ctx.search, hits)}
    @rt('/code/sync')
    async def code_sync():
        try: return await ctx.search.async_sync(True, True)
        except Exception as e: return fail(e)
    @rt('/similar')
    async def similar_route(path: str, line: int = 1, mode: str = 'cluster', limit: int = 25):
        "Code like the function at `path:line`: `mode=cluster` for the family it belongs to, `mode=knn`."
        fn = ctx.search.peers if mode == 'cluster' else ctx.search.similar
        return found(ctx.search, await off_loop(fn, path, line, limit=limit))
    @rt('/search/events')
    async def search_events(req):
        """What was asked, shown, previewed and opened. Recording never fails a search, so a
        problem is reported in `note` and the batch is dropped."""
        try: d = await req.json()
        except Exception: return fail('expected a JSON batch')
        held = prefs()
        mode = str(held.get('telemetry') or 'vault')
        if mode == 'off': return {'ok': True, 'recorded': 0, 'note': 'search telemetry is off'}
        n = await off_loop(signals.record, d.get('events') or [], bool(held.get('snippets')))
        session, remembered = d.get('session') or {}, False
        if mode == 'vault' and session:
            # The vault write loads an encoder, so it happens off the request. A search must never
            # wait on it, and a vault that will not open must never lose the event log.
            asyncio.ensure_future(remember(session))
            remembered = True
        return {'ok': True, 'recorded': n, 'remembering': remembered, 'note': signals.note}
    @rt('/search/signals')
    async def search_signals(days: int = 30):
        "The metrics a ranker is tuned from, and where they were read."
        held = prefs()
        return {'ok': True, 'telemetry': held.get('telemetry', 'vault'),
            'snippets': bool(held.get('snippets')), 'dir': str(signals.dir),
            'vault': str(search_vault_path()), 'weights': Weights.load(held).settings(),
            'defaults': Weights().settings(), 'keys': SETTING_WEIGHTS,
            'summary': await off_loop(signals.summary, days)}
    @rt('/search/signals/purge')
    async def search_signals_purge():
        "Delete every event file. The vault documents are left alone; the vault surfaces own those."
        return {'ok': True, 'removed': await off_loop(signals.purge)}
    @rt('/clusters')
    async def clusters_route(limit: int = 40):
        "An ANN clustering of the whole indexed corpus: a map of the codebase by embedding distance."
        cs = await off_loop(ctx.search.clusters)
        return {'note': ctx.search.note, 'clusters': [c.dict() for c in cs[:limit]]}
