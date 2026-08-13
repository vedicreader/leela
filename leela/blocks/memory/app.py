"""Durable prose memory: fetched pages, research briefs, and what the agent may recall.

Retrieval routes touch only `ctx.memory`, a `MemoryPort`, so the concrete `Memory` is never
named here. `/memory/forget` and `/memory/purge` also reach `ctx.session`: which notes enter
model context is a per-surface selection in workspace state, and it must drop what is forgotten.
"""

from __future__ import annotations

from ...core.web import fail, off_loop

__all__ = ['CAPS', 'connect']

CAPS = ('memory',)


def _drop_from_selection(session, removed):
    "Forget `removed` in every surface's note selection, then re-brief live assistants."
    # Not `Workspace._rebrief_agents`: that swallows exceptions, and these routes let a failing
    # `refresh()` surface as a 500.
    sel = session.agent_memory_selection
    for target, ids in sel.items(): sel[target] = [v for v in ids if v not in removed]
    session.save()
    for assistant in (session._ai, session._inline_ai):
        if assistant is not None: assistant.refresh()


def connect(app, ctx):
    rt = app.route

    @rt('/memory/info')
    async def memory_info():
        status = await off_loop(ctx.memory.status)
        docs = await off_loop(ctx.memory.documents, 80)
        return {**status, 'items': docs}

    @rt('/memory/forget')
    async def memory_forget(req):
        d = await req.json()
        doc_id = str(d.get('id') or '')
        ok = await off_loop(ctx.memory.forget, doc_id)
        if ok: _drop_from_selection(ctx.session, {doc_id})
        return {'ok': ok, 'note': ctx.memory.note}

    @rt('/memory/purge')
    async def memory_purge(req):
        d = await req.json()
        ids = d.get('ids')
        if ids is not None and not isinstance(ids, list): return fail('ids must be a list')
        # `ids=None` means every agent note, so read the ids to un-select before the purge.
        removed_ids = ({str(value) for value in ids} if ids is not None else
            {str(note['id']) for note in await off_loop(ctx.memory.agent_notes)})
        removed = await off_loop(ctx.memory.purge, ids)
        _drop_from_selection(ctx.session, removed_ids)
        return dict(ok=True, removed=removed, note=ctx.memory.note)

    @rt('/memory/search')
    async def memory_search(q: str = '', limit: int = 8):
        rows = await off_loop(ctx.memory.search, q, min(30, max(1, int(limit))))
        return {'note': ctx.memory.note, 'results': rows}

    @rt('/memory/toc')
    async def memory_toc(doc: str = '', depth: int = 3):
        rows = await off_loop(ctx.memory.toc, doc or None, depth)
        return {'note': ctx.memory.note, 'documents': rows}

    @rt('/memory/read')
    async def memory_read(node: str = ''): return {'note': ctx.memory.note, 'section': await off_loop(ctx.memory.read, node)}

    @rt('/memory/clusters')
    async def memory_clusters(limit: int = 20): return await off_loop(ctx.memory.clusters, min(50, max(1, int(limit))))
