from __future__ import annotations

import json, re

from fastcore.all import Path
from fasthtml.common import Button, Div, Span

from ... import errstr
from ...core.web import fail, off_loop
from ..memory.memory import source_kind
from ..tabs.ui import tab_bar
from . import ui
from .ui import PII_COVERS, job_card, pii_badge, vault_browse, vault_panel, vault_tree

__all__ = ['CAPS', 'connect', 'job_card', 'pii_badge', 'vault_panel', 'PII_COVERS']

CAPS = ('fs', 'memory', 'search', 'jobs', 'tab', 'vaults', 'feeds')

def connect(app, ctx):
    rt = app.route
    try: ctx.jobs.recover()
    except Exception: pass
    @rt('/jobs')
    def jobs_list(kind: str = '', limit: int = 40):
        try: return dict(jobs=[j.dict() for j in ctx.jobs.all(limit=limit, kind=kind or None)], note=ctx.jobs.note)
        except Exception as e: return fail(e)
    @rt('/jobs/{jid}')
    def job_one(jid: str):
        try: return job_card(ctx.jobs.get(jid))
        except Exception as e: return fail(e)
    @rt('/jobs/{jid}/forget')
    def job_forget(jid: str):
        try: return {'ok': True, 'id': ctx.jobs.forget(jid).id}
        except Exception as e: return fail(e)
    @rt('/jobs/{jid}/retry')
    def job_retry(jid: str):
        try: return job_card(ctx.jobs.launch(jid))
        except Exception as e: return fail(e)
    @rt('/clip')
    def clip(target: str, kind: str = 'clip', shelf: str = '', origin: str = ''):
        try:
            if kind not in ('clip', 'clip_tree', 'clip_codebase', 'clip_api_spec'):
                raise ValueError(f'unknown clip kind {kind!r}')
            return job_card(ctx.jobs.start(kind, target, shelf=shelf or None, **{'from': origin} if origin else {}))
        except Exception as e: return fail(e)
    @rt('/vault/panel')
    def panel():
        try:
            roots = ctx.fs.roots
            return vault_panel(ctx.memory, ctx.jobs, active_path=getattr(ctx.tab, 'path', '') or '',
                root=str(roots[0]) if roots else '', vaults=ctx.vaults.dict())
        except Exception as e: return fail(e)
    @rt('/vault/shelves')
    def shelves():
        try: return dict(shelves=ctx.memory.shelves(), note=ctx.memory.note)
        except Exception as e: return fail(e)
    @rt('/vault/pii')
    async def vault_pii(doc: str, shelf: str = ''):
        try:
            r = await off_loop(ctx.memory.pii, doc, shelf or None)
            return dict(r, covers='titled names and pattern kinds; a bare name is not found')
        except Exception as e: return fail(e)
    @rt('/vault/pii/badge')
    async def vault_pii_badge(doc: str, shelf: str = ''):
        try: return pii_badge(await off_loop(ctx.memory.pii, doc, shelf or None))
        except Exception as e: return Span('pii unavailable', cls='lee-pii', title=errstr(e))
    @rt('/vault/tidy')
    def tidy(shelf: str = '', k: int = 20):
        try: return job_card(ctx.jobs.start('tidy', shelf or '', shelf=shelf or None, k=k))
        except Exception as e: return fail(e)
    @rt('/vault/reindex')
    async def vault_reindex(shelf: str = ''):
        try:
            r = await off_loop(ctx.memory.reindex_changed, [shelf] if shelf else None)
            said = (f"re-indexed {r['reindexed']} of {r['checked']} filed documents" +
                    (f" · {len(r['missing'])} missing" if r['missing'] else '') +
                    (f" · {len(r['failed'])} failed" if r['failed'] else ''))
            return Div(Div(said, cls='lee-vault-empty'), id='vaulttidy', cls='lee-vault-tidyrows')
        except Exception as e: return fail(e)
    @rt('/vault/tidy/list')
    async def tidy_list(shelf: str = '', k: int = 20):
        try: return await off_loop(ui.tidy_list, ctx.memory, shelf, k)
        except Exception as e: return fail(e)
    @rt('/vault/noisy')
    async def mark_noisy(doc: str, shelf: str = '', noisy: bool = True, reason: str = ''):
        try:
            await off_loop(lambda: ctx.memory.mark_noisy(doc, shelf=shelf or None, noisy=noisy, reason=reason))
            return Div(Span('dropped from search' if noisy else 'kept', cls='lee-tidy-judged'),
                Span(doc, cls='lee-tidy-title', title=doc), cls='lee-tidy-row judged')
        except Exception as e: return fail(e)
    @rt('/vault/watches')
    def watches(shelf: str = '', due_only: bool = False):
        try: return dict(watches=ctx.memory.watches(shelf=shelf or None, due_only=due_only),
            actions=('url', 'web', 'crawl', 'arxiv', 'youtube', 'remind'))
        except Exception as e: return fail(e)
    @rt('/vault/watch')
    async def watch(target: str, action: str = 'url', every: str = '1d', note: str = '', shelf: str = ''):
        try:
            if not target.strip(): raise ValueError('nothing to watch')
            await off_loop(lambda: ctx.memory.watch(target, action=action, every=every,
                note=note or None, shelf=shelf or None))
            return ui.watch_list(ctx.memory.watches(shelf=shelf or None))
        except Exception as e: return fail(e)
    @rt('/vault/unwatch')
    async def unwatch(watch_id: str, shelf: str = ''):
        try:
            await off_loop(ctx.memory.unwatch, watch_id, shelf or None)
            return ui.watch_list(ctx.memory.watches(shelf=shelf or None))
        except Exception as e: return fail(e)
    @rt('/vault/poll')
    def poll():
        try: return job_card(ctx.jobs.start('poll'))
        except Exception as e: return fail(e)
    def _mem(vault=''):
        return ctx.vaults.memory(vault or None)
    def _elid(spec):
        return re.sub(r'[^A-Za-z0-9_-]', '', str(spec or ''))[:40] or 'vaultbrowse'
    def _open(spec):
        return None if spec is None else tuple(x for x in str(spec).split('|') if x)
    def _writable(vault='', who='you'):
        ref = ctx.vaults.get(vault or None)
        if ref is None: raise KeyError(vault)
        ok = ref.agent_writable if who == 'agent' else ref.writable
        if not ok: raise PermissionError(f'{ref.name} is attached read-only')
        return ref
    @rt('/vault/list')
    def vault_list():
        try: return ctx.vaults.dict()
        except Exception as e: return fail(e)
    @rt('/vault/attach')
    def vault_attach(path: str, name: str = '', access: str = 'read'):
        try: return dict(ctx.vaults.attach(path, name=name, access=access).dict(), note=ctx.vaults.note)
        except Exception as e: return fail(e)
    @rt('/vault/create')
    def vault_create(path: str, name: str = ''):
        try: return dict(ctx.vaults.create(path, name=name).dict(), note=ctx.vaults.note)
        except Exception as e: return fail(e)
    @rt('/vault/detach')
    def vault_detach(name: str):
        try: return dict(ctx.vaults.detach(name).dict(), note=ctx.vaults.note)
        except Exception as e: return fail(e)
    @rt('/vault/activate')
    def vault_activate(name: str, wb: bool = False):
        try:
            ref = ctx.vaults.activate(name)
            if wb: return ui.workbench(_mem(ref.name), ctx.vaults, 'browse', vault=ref.name)
            return dict(ref.dict(), note=ctx.vaults.note)
        except Exception as e: return fail(e)
    @rt('/vault/access')
    def vault_access(name: str, access: str = '', agent: str = ''):
        try:
            if access: ctx.vaults.set_access(name, access)
            if agent: ctx.vaults.set_agent(name, agent.lower() in ('1', 'true', 'yes', 'on'))
            ref = ctx.vaults.get(name)
            if ref is None: raise KeyError(name)
            return dict(ref.dict(), note=ctx.vaults.note)
        except Exception as e: return fail(e)
    @rt('/vault/documents')
    async def vault_documents(vault: str = '', shelf: str = '', kind: str = '', limit: int = 200):
        try:
            m = _mem(vault)
            rows = await off_loop(m.all_documents, limit, [shelf] if shelf else None, kind or None)
            return {'documents': rows, 'shelves': m.shelves(), 'vault': ctx.vaults.get(vault or None).dict(),
                    'note': m.note}
        except Exception as e: return fail(e)
    @rt('/vault/search')
    async def vault_search(q: str, vault: str = '', shelf: str = '', limit: int = 20):
        try:
            m = _mem(vault)
            hits = await off_loop(m.search_all, q, limit, [shelf] if shelf else None)
            return {'query': q, 'hits': hits, 'note': m.note}
        except Exception as e: return fail(e)
    @rt('/vault/mentions')
    async def vault_mentions(q: str = '', vault: str = '', limit: int = 8):
        try:
            m, want = _mem(vault), q.strip().lower()
            docs = await off_loop(m.all_documents, 400, None, None)
            named = [d for d in docs if not want or want in str(d.get('title') or '').lower()][:limit]
            out = [{'kind': 'document', 'doc': d.get('doc_id') or d.get('id'), 'shelf': d.get('shelf', ''),
                    'vault': vault or ctx.vaults.active.name, 'title': d.get('title') or 'untitled',
                    'detail': f"{d.get('kind') or 'document'} · {d.get('shelf', '')}"} for d in named]
            if want and len(out) < limit:
                hits = await off_loop(m.search_all, q, limit - len(out), None)
                # the whole node id, not the document it sits in: attaching a section is the point
                out += [{'kind': 'section', 'doc': str(h.get('node_id') or ''),
                         'shelf': h.get('shelf', ''), 'vault': vault or ctx.vaults.active.name,
                         'title': h.get('breadcrumb') or h.get('title') or 'section',
                         'detail': f"section · {h.get('shelf', '')}"} for h in hits]
            return {'mentions': out, 'note': m.note}
        except Exception as e: return fail(e)
    @rt('/vault/doc')
    async def vault_doc(doc: str, vault: str = '', shelf: str = ''):
        try:
            m = _mem(vault)
            row = await off_loop(m.document, doc, shelf or None)
            if not row: return fail('no such document', 404)
            privacy = await off_loop(m.pii, doc, shelf or None)
            evidence = await off_loop(m.pii_evidence, doc, shelf or None) if privacy.get('has_pii') else []
            return {'doc': row, 'shelf': shelf, 'sections': await off_loop(m.sections, doc, shelf or None),
                    'privacy': privacy, 'evidence': evidence, 'covers': PII_COVERS, 'note': m.note}
        except Exception as e: return fail(e)
    @rt('/vault/section')
    async def vault_section(node: str, vault: str = '', shelf: str = ''):
        try:
            m = _mem(vault)
            sec = await off_loop(m.shelf_read, node, shelf or None)
            if not sec: return fail('no such section', 404)
            return {'section': sec, 'related': await off_loop(m.related, node, shelf or None), 'note': m.note}
        except Exception as e: return fail(e)
    def _refused(e):
        return fail(e, 403 if isinstance(e, PermissionError) else 400)
    @rt('/vault/shelf/move')
    async def vault_move(doc: str, target: str, vault: str = '', shelf: str = ''):
        try:
            _writable(vault)
            return await off_loop(_mem(vault).move, doc, target, shelf or None)
        except Exception as e: return _refused(e)
    @rt('/vault/shelf/drop')
    async def vault_drop_shelf(shelf: str, vault: str = ''):
        try:
            _writable(vault)
            return await off_loop(_mem(vault).drop_shelf, shelf)
        except Exception as e: return _refused(e)
    @rt('/vault/not-pii')
    async def vault_not_pii(doc: str, vault: str = '', shelf: str = '', clear: bool = True, reason: str = ''):
        try:
            _writable(vault)
            m = _mem(vault)
            await off_loop(m.mark_not_pii, doc, shelf or None, clear, reason)
            return {'ok': True, 'privacy': await off_loop(m.pii, doc, shelf or None), 'covers': PII_COVERS}
        except Exception as e: return _refused(e)
    @rt('/vault/open')
    def vault_open(doc: str, shelf: str = '', vault: str = '', title: str = ''):
        try:
            ctx.session.open_vault_doc(doc, shelf=shelf, vault=vault, title=title)
            return tab_bar(ctx.session)
        except Exception as e: return fail(e)
    @rt('/vault/workbench/open')
    def workbench_open(view: str = 'browse'):
        try:
            ctx.session.open_vault_workbench(view)
            return tab_bar(ctx.session)
        except Exception as e: return fail(e)
    @rt('/vault/find')
    async def vault_find():
        try:
            seen = {r['path'] for r in ctx.vaults.dict().get('vaults', [])}
            found, roots = [], [Path('~/.vishalakshi').expanduser(), Path('~/.leela').expanduser(),
                                *[Path(r) for r in ctx.fs.roots]]
            for root in roots:
                if not root.is_dir(): continue
                for p in sorted(root.glob('*.db')) + sorted(root.glob('*/vault.db')):
                    if str(p) in seen or not p.is_file(): continue
                    found.append({'path': str(p), 'name': p.parent.name if p.name == 'vault.db' else p.stem,
                                  'bytes': p.stat().st_size})
            return Div(*([Button(f"{f['name']} · {round(f['bytes'] / 1024)}kb", cls='lee-vault-found',
                                 title=f['path'], hx_post='/vault/attach', hx_target='#vaultpanel',
                                 hx_swap='none', hx_vals=json.dumps({'path': f['path'], 'name': f['name']}))
                          for f in found] or [Span('no unattached vaults found', cls='lee-dim')]),
                       id='vaultfound', cls='lee-vault-found-rows')
        except Exception as e: return fail(e)
    @rt('/vault/source')
    def vault_source(doc: str, shelf: str = '', vault: str = ''):
        try:
            row = _mem(vault).document(doc, shelf or None)
            src = str(row.get('source') or '')
            kind = source_kind(src)
            if kind != 'file': return {'ok': True, 'kind': kind, 'path': src, 'exists': False,
                                       'inside_workspace': False}
            p = Path(src).expanduser()
            return {'ok': True, 'kind': 'file', 'path': str(p), 'exists': p.is_file(),
                    'inside_workspace': ctx.fs.covers(p), 'parent': str(p.parent)}
        except Exception as e: return fail(e)
    @rt('/vault/browse')
    async def vault_browse_route(q: str = '', vault: str = '', shelf: str = '', limit: int = 60,
                                 open: str = None, elid: str = 'vaultbrowse'):
        try: return await off_loop(vault_browse, _mem(vault), q, vault, shelf, limit, _open(open), _elid(elid))
        except Exception as e: return fail(e)
    @rt('/vault/tree')
    async def vault_tree_route(vault: str = '', shelf: str = '', open: str = None, limit: int = 2000,
                               elid: str = 'vaultbrowse'):
        try: return await off_loop(vault_tree, _mem(vault), vault, shelf, _open(open), limit, _elid(elid))
        except Exception as e: return fail(e)

    def _root(): return str(ctx.fs.roots[0]) if ctx.fs.roots else ''
    @rt('/vault/workbench')
    async def workbench(view: str = 'browse', vault: str = '', shelf: str = '', q: str = '',
                        src: str = '', match: str = '', feed: str = '', name: str = ''):
        try:
            body = await off_loop(_view, view, vault, shelf, q, src, match, feed, name)
            ctx.session.note_vault_view(view)
            return ui.workbench(_mem(vault), ctx.vaults, view, body=body)
        except Exception as e: return fail(e)
    def _view(view, vault='', shelf='', q='', src='', match='', feed='', name=''):
        m = _mem(vault)
        if view == 'find': return ui.find_view(m, vault, q=q, shelf=shelf)
        if view == 'add': return ui.add_view(m, vault, jobs=ctx.jobs, root=_root())
        if view == 'news': return ui.news_view(m, vault, feeds=ctx.feeds, q=q, feed=feed)
        if view == 'specs': return ui.specs_view(m, vault, **_spec_kw(src, match, name))
        if view == 'topics': return ui.topics_view(m, vault)
        return ui.browse_view(m, vault, shelf=shelf, q=q)
    def _api_host():
        "A host over this workspace: the specs it loads live on the workspace, so the agent has them."
        from ..agent.ai import WorkspaceHost
        return WorkspaceHost(ctx.session)
    def _spec_kw(src='', match='', name=''):
        from .spec import CREDS
        kw = dict(src=src, match=match, creds=CREDS.policies())
        if not src.strip(): return kw
        try:
            host = _api_host()
            key = host.api_load(src, name)['name']
            return dict(kw, ops=host.api_ops(name=key, match=match, limit=0), name=key)
        except Exception as e: return dict(kw, error=errstr(e))
    @rt('/vault/view/{view}')
    async def workbench_view(view: str, vault: str = '', shelf: str = '', q: str = '',
                             src: str = '', match: str = '', feed: str = '', name: str = ''):
        try:
            body = await off_loop(_view, view, vault, shelf, q, src, match, feed, name)
            ctx.session.note_vault_view(view)     # the swap is the tab moving, and it outlives it
            return body
        except Exception as e: return fail(e)
    @rt('/vault/apis/form')
    def apis_form(operation: str = '', name: str = ''):
        "One row's operation, moved into the call form rather than typed out of the table."
        try: ops = _api_host().api_ops(name=name, limit=0) if name else ()
        except Exception: ops = ()
        return ui.call_panel(name, operation, '', ops)
    @rt('/vault/apis/call')
    async def apis_call(operation: str, name: str = '', params: str = ''):
        """Call one operation and show what came back.

        `api_fetch`, not `api_call`: the reach gate is about a model reading the answer, and the
        person looking at this page is the person whose data it is.
        """
        try:
            kw = json.loads(params) if str(params or '').strip() else {}
            if not isinstance(kw, dict): raise ValueError('the parameters must be a JSON object')
            out = await off_loop(lambda: _api_host().api_fetch(operation, name=name, **kw))
            return ui.api_result(out, f'{operation} answered')
        except Exception as e: return Div(errstr(e), cls='lee-job-error')
    @rt('/vault/plan')
    async def vault_plan(target: str, vault: str = ''):
        try:
            from .acquire import plan_tree
            return ui.import_plan(await off_loop(plan_tree, target))
        except Exception as e: return Div(errstr(e), cls='lee-job-error')
    @rt('/vault/acquire')
    def vault_acquire(target: str, action: str = '', shelf: str = '', vault: str = ''):
        try:
            from .acquire import detect
            if not target.strip(): raise ValueError('nothing to bring in')
            act = action or detect(target)
            kind = 'clip' if act == 'clip' else 'acquire'
            return job_card(ctx.jobs.start(kind, target, action=act, shelf=shelf or None))
        except Exception as e: return fail(e)
    @rt('/vault/note')
    async def vault_note(text: str, title: str = '', shelf: str = '', vault: str = ''):
        try:
            _writable(vault)
            if not text.strip(): raise ValueError('nothing to keep')
            row = await off_loop(lambda: _mem(vault).acquire('note', text, shelf=shelf or None,
                title=title or None))
            return Div(Span('note', cls='lee-job-kind'), Span('complete', cls='lee-job-status complete'),
                Span(title or str(row.get('title') or 'note'), cls='lee-job-target'), cls='lee-job complete')
        except Exception as e: return _refused(e)
    @rt('/vault/connect')
    def vault_connect(vault: str = ''):
        try: return job_card(ctx.jobs.start('connect'))
        except Exception as e: return fail(e)
    def _read_now(vault, only):
        "Read one source on the way in: a cadence says when to read it *again*."
        from .news import poll_feeds
        m = _mem(vault)
        try: poll_feeds(m, ctx.feeds, only=only)
        except Exception as e: return ui.news_view(m, vault, feeds=ctx.feeds, error=errstr(e))
        return ui.news_view(m, vault, feeds=ctx.feeds)
    @rt('/vault/apis/creds')
    def apis_creds(name: str, headers: str = '', reach: str = 'cloud'):
        "Keep one spec's headers and who may call it. The values go where leela keeps secrets."
        from .spec import CREDS, parse_headers
        try: CREDS.set(name, parse_headers(headers), reach=reach)
        except Exception as e: return ui.creds_view(CREDS.policies(), error=errstr(e))
        return ui.creds_view(CREDS.policies(), error=CREDS.note)
    @rt('/vault/news/add')
    async def news_add(url: str, title: str = '', every: str = '1h', vault: str = ''):
        try:
            f = await off_loop(ctx.feeds.add, url, title, every)
            return await off_loop(_read_now, vault, f.id)
        except Exception as e: return ui.news_view(_mem(vault), vault, feeds=ctx.feeds, error=errstr(e))
    @rt('/vault/news/pull')
    async def news_pull(fid: str, vault: str = ''):
        try: return await off_loop(_read_now, vault, fid)
        except Exception as e: return ui.news_view(_mem(vault), vault, feeds=ctx.feeds, error=errstr(e))
    @rt('/vault/news/remove')
    def news_remove(fid: str, vault: str = ''):
        try:
            ctx.feeds.remove(fid)
            return ui.news_view(_mem(vault), vault, feeds=ctx.feeds)
        except Exception as e: return ui.news_view(_mem(vault), vault, feeds=ctx.feeds, error=errstr(e))
    @rt('/vault/news/toggle')
    def news_toggle(fid: str, enabled: bool = None, vault: str = ''):
        try:
            ctx.feeds.toggle(fid, enabled)
            return ui.news_view(_mem(vault), vault, feeds=ctx.feeds)
        except Exception as e: return ui.news_view(_mem(vault), vault, feeds=ctx.feeds, error=errstr(e))
    @rt('/vault/news/poll')
    def news_poll(force: bool = False):
        try: return job_card(ctx.jobs.start('feeds', force=force))
        except Exception as e: return fail(e)
    @rt('/vault/news/feeds')
    def news_feeds():
        try: return ctx.feeds.dict()
        except Exception as e: return fail(e)
