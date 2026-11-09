from __future__ import annotations

import asyncio, json, os, re, shutil, sqlite3
from datetime import datetime
from collections import Counter

from fastcore.all import AttrDict, L, Path, first
from fasthtml.common import Button, Div, Span
from starlette.requests import Request
from starlette.responses import Response

from ... import errstr
from ...core.web import fail, off_loop, sse
from ..memory.memory import VERSE_SCRIPT, PrivacyBlocked, VaultRefused, counts_list, page_list, source_kind
from ..memory.vaults import LEARN, learn_path
from ..tabs.ui import tab_bar
from . import ui
from .jobs import CLIPS
from .ui import PII_COVERS, job_card, pii_badge, vault_browse, vault_panel, vault_tree

__all__ = ['CAPS', 'connect', 'job_card', 'pii_badge', 'vault_panel', 'PII_COVERS', 'read_choice', 'reader_id', 'chat_spec',
           'ask_chat', 'Streamed']

CAPS = ('fs', 'memory', 'jobs', 'vaults', 'feeds', 'tab')

def read_choice(d):
    "A Read sheet choice as it may be remembered, or None. `allow` is never kept: allow once is once."
    from vishalakshi.read import PARSE, PRESETS
    if not isinstance(d, dict) or d.get('parse', 'auto') not in PARSE or d.get('preset', 'generic') not in PRESETS: return None
    out = {'parse': d.get('parse', 'auto'), 'preset': d.get('preset', 'generic'),
           'model': str(d.get('model') or ''), 'hint': str(d.get('hint') or '')}
    if isinstance(rs := d.get('readers'), list) and rs: out['readers'] = [str(r) for r in rs if r][:4]
    if isinstance(a := d.get('agree'), int) and a > 0: out['agree'] = a
    if d.get('book') is True and out['preset'] in VERSE_SCRIPT: out['book'] = True
    return out

def reader_id(name):
    "A Leela model name as the id vishalakshi reads page images with; `model_unavailable` when it cannot."
    if not name: return None
    from ...agent.core import resolve, spec_caps
    try: spec = resolve(name)
    except Exception as e: raise VaultRefused(f'{name} is not available here ({errstr(e)})', 'model_unavailable') from e
    if spec is None: raise VaultRefused(f'{name} is not available here', 'model_unavailable')
    try: caps = spec_caps(spec)
    except Exception: caps = None
    if caps is not None and 'image' not in caps.inp: raise VaultRefused(f'{name} does not read images', 'model_unavailable')
    return spec.model_id

def chat_spec(name):
    "The model a text send goes to, placed on or off this machine; `model_unavailable` when it does not resolve. Tests put a stand-in here."
    from ...agent.core import resolve
    try: s = resolve(name)
    except Exception as e: raise VaultRefused(f'{name or "the default model"} is not available here ({errstr(e)})', 'model_unavailable') from e
    return AttrDict(name=name or s.name, local=bool(s.local), model_id=s.model_id, runtime=s.runtime, ctx=s.ctx)

def ask_chat(spec):
    "The chat factory Find > Ask builds for `spec`, in `Vault.ask`'s `mk_chat` shape. Tests put a stand-in here."
    def mk(_model=None, **kw):
        from rishi import Chat
        return Chat(spec.model_id, runtime=spec.runtime, ctx_limit=spec.ctx, **kw)
    return mk

class Streamed:
    "A chat that hands the text so far to `put` as it streams, and answers with all of it, as `Vault.ask` reads a reply."
    def __init__(self, ch, put): self.ch, self.put = ch, put
    def __getattr__(self, k): return getattr(self.ch, k)
    def __call__(self, prompt, **kw):
        from urai import resp_text
        self.put('reset', '')     # a retry with less context asks again from nothing
        r, text = self.ch(prompt, stream=True, **kw), ''
        for x in ([r] if isinstance(r, (str, dict)) else r):
            text += x if isinstance(x, str) else resp_text(x)
            self.put('chunk', text)
        return {'role': 'assistant', 'content': text}

def _plain(o): return json.loads(json.dumps(o, default=lambda x: list(x) if isinstance(x, (L, set, tuple)) else str(x)))

def _standalone_vault():
    p = os.getenv('ABHYASA_VAULT') or os.getenv('VISHALAKSHI_VAULT') or str(Path.home()/'.vishalakshi'/'vault.db')
    p = Path(p).expanduser()
    return p if p.is_file() else None

def _backup_path(src):
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    return src.with_name(f'{src.stem}.{stamp}.backup{src.suffix}')

def _copy_learning(src, con):
    "Copy the learning shelf of the vault file `src` into the open vault connection `con` in one transaction, so a failure leaves it as it was."
    con.execute('attach database ? as old', (str(src),))
    try:
        names = {r['name'] for r in con.q("select name from old.sqlite_master where type='table'")}
        con.execute('begin immediate')
        try:
            for name in ('learning', 'learning_docs', 'learning_nodes', 'learning_sources'):
                if name not in names: continue
                cols = ','.join(f"[{r['name']}]" for r in con.q(f'pragma old.table_info([{name}])'))
                con.execute(f'delete from main.[{name}]')
                con.execute(f'insert into main.[{name}] ({cols}) select {cols} from old.[{name}]')
            con.execute("insert into main.[learning_fts]([learning_fts]) values('rebuild')")
            con.execute('commit')
        except BaseException:
            con.execute('rollback'); raise
    finally: con.execute('detach database old')

def _shelf_counts(p):
    "`(walks, concepts)` on the learning shelf of the vault file `p`, read-only; `(0, 0)` when it has none or cannot be read."
    try:
        con = sqlite3.connect(f'file:{p}?mode=ro', uri=True)
        try: n = dict(con.execute("select kind, count(*) from learning_docs where kind in ('journey', 'concept') group by kind"))
        finally: con.close()
        return n.get('journey', 0), n.get('concept', 0)
    except Exception: return 0, 0

def _offer(vaults, again=False):
    "`(source, walks, concepts)` when the Learn vault is not set up and a standalone vault holds learning, else None."
    src, ref = _standalone_vault(), vaults.get(LEARN)
    if src is None: return
    if ref is not None:
        if ref.imported_from or (ref.skipped and not again) or sum(_shelf_counts(ref.path)): return
        if ref.exists and src.resolve() == Path(ref.path).resolve(): return
    w, c = _shelf_counts(src)
    return (src, w, c) if w + c else None

def _refusal(e):
    "Any failure as the shared shape: a `VaultRefused` keeps its kind and status."
    if isinstance(e, VaultRefused): return fail(e, e.code, kind=e.kind, **e.extra)
    if isinstance(e, PermissionError) and not getattr(e, 'kind', None): return fail(e, 403, kind='read_only')
    if isinstance(e, (KeyError, FileNotFoundError)): return fail(e, 404, kind='not_found')
    return fail(e, kind=getattr(e, 'kind', None) or 'failed')

def _do_learn_import(ctx, src, ref, choice):
    "Attach, copy or skip; the one result dict every route that reaches this state returns."
    if choice not in ('attach', 'copy', 'skip'): raise VaultRefused('choice must be attach, copy or skip', 'bad_choice')
    if ref is not None and ref.imported_from: raise VaultRefused('Learning data was already imported.', 'already_imported', 409)
    if choice == 'skip':
        ref = ctx.vaults._replace(ctx.vaults.learn(), skipped=True)
        return {'ok': True, 'vault': ref.name, 'choice': 'skip'}
    if src is None: raise VaultRefused('No standalone Abhyasa vault was found.', 'none_found', 404)
    if ref is not None and sum(_shelf_counts(ref.path)): raise VaultRefused('The Learn vault already holds learning, so nothing was changed.', 'learn_not_empty', 409)
    if choice == 'attach':
        if not os.access(src, os.W_OK): raise VaultRefused(f'{src.name} is read-only, so Learn cannot open it in place. Use Back up and copy.', 'read_only', 403)
        ref = ctx.vaults.import_learn(src)
        return {'ok': True, 'vault': ref.name, 'choice': 'attach', 'access': ref.access}
    try:
        backup = _backup_path(src); shutil.copy2(src, backup)
    except Exception as e: raise VaultRefused(f'The backup failed, so nothing was copied and your learning data is untouched ({errstr(e)}).', 'backup_failed', 500) from e
    ref = ctx.vaults.learn()
    try: _copy_learning(src, ctx.vaults.memory(ref.name)._store('learning').db)
    except Exception as e: raise VaultRefused(f'The copy failed and was undone. Your learning data is untouched in {src.parent.name}, and a backup is {backup.name} ({errstr(e)}).', 'copy_failed', 500) from e
    ref = ctx.vaults._replace(ref, imported_from=str(src.resolve()), skipped=False)
    return {'ok': True, 'vault': ref.name, 'choice': 'copy', 'backup': str(backup)}

def connect(app, ctx):
    rt = app.route
    def tracker(job, report):
        "A vishalakshi `progress` that puts pages done, the route mix and the cost on the card, and stops once the card is cancelled."
        st = dict(routes=Counter(), cost=0.0)
        def progress(done, total, page, route, cost):
            if route: st['routes'][route] += 1
            st['cost'] += cost or 0
            mix = ', '.join(f'{k} {n}' for k, n in st['routes'].items())
            report(progress=.1 + .85 * done / max(1, total), current=f'{done} of {total} pages' + (f' · {mix}' if mix else '') +
                   (f" · ${st['cost']:.4f}" if st['cost'] else ''))
            return not ctx.jobs.stopping(job.id)
        return progress
    def spend_allow(job, report):
        "Allow once is spent by the run it was given to: a retry or a resume asks again."
        p = dict(job.params)
        allow = bool(p.pop('allow', False))
        if allow: report(params=p)
        return p, allow
    KEEP = ('doc_id', 'title', 'shelf', 'level', 'routes', 'flagged', 'blocked', 'kind', 'nodes', 'chunks', 'cost', 'model_pages',
            'cancelled', 'unread', 'pages', 'changed', 'changes', 'proposed', 'chapters', 'verses', 'problems', 'counts')
    def result(out, p):
        return {k: out[k] for k in KEEP if k in out} | {'vault': p.get('vault') or ctx.vaults.active.name, 'model': p.get('name') or p.get('model') or ''}
    def read_job(job, report):
        p, allow = spend_allow(job, report)
        report(progress=0.1, current=f'reading {Path(job.target).name}')
        m = ctx.vaults.memory(p.get('vault') or None)
        # a resumed read re-reads only its unread pages: reading the file again would file the text layer over pages a model read
        if p.get('resume'): return result(m.reparse(p['resume'], p.get('shelf') or None, p.get('pages'), p.get('model'), p.get('preset') or None,
                                                    p.get('hint') or None, ctx.session.vault_pii, allow, tracker(job, report)), p) | {'doc_id': p['resume']}
        out = m.read_file(job.target, p.get('shelf') or None, p.get('parse', 'auto'), p.get('model') or None,
                     p.get('preset', 'generic'), p.get('hint', ''), p.get('pages'), ctx.session.vault_pii, allow, p.get('level') or None,
                     progress=tracker(job, report))
        try: m.guess_type(out['doc_id'], out.get('shelf'))
        except Exception: pass
        return result(out, p)
    def extract_job(job, report):
        p = dict(job.params)
        report(progress=0.2, current=f"reading fields with {p.get('name') or 'the default model'}")
        out = ctx.vaults.memory(p.get('vault') or None).extract(job.target, p.get('shelf') or None, p.get('model'), p.get('chat_kw'),
                                                                p.get('pii') or 'redact', p.get('name') or '')
        return out | {'title': p.get('title') or '', 'shelf': p.get('shelf') or '', 'vault': p.get('vault') or ctx.vaults.active.name}
    def reparse_job(job, report):
        p, allow = spend_allow(job, report)
        m = ctx.vaults.memory(p.get('vault') or None)
        out = m.reparse(job.target, p.get('shelf') or None, p.get('pages'), p.get('model'), p.get('preset') or None, p.get('hint') or None,
                        ctx.session.vault_pii, allow, tracker(job, report))
        return result(out, p) | {'title': p.get('title') or ''}
    def proof_job(job, report):
        p, allow = spend_allow(job, report)
        m = ctx.vaults.memory(p.get('vault') or None)
        out = m.proofread(job.target, p.get('readers') or [], p.get('shelf') or None, p.get('pages'), int(p.get('agree') or 2),
                          ctx.session.vault_pii, allow, tracker(job, report))
        return result(out, p) | {'title': p.get('title') or '', 'blocked': out.get('blocked') or []}
    def book_job(job, report):
        "Read every page by model, a new file or a filed document again, then assemble the verses; a cancelled read assembles what it read."
        p, allow = spend_allow(job, report)
        m, sh, pol = ctx.vaults.memory(p.get('vault') or None), p.get('shelf') or None, ctx.session.vault_pii
        if did := p.get('resume') or (job.target if p.get('again') else None):
            out = dict(m.reparse(did, sh, p.get('pages'), p.get('model'), p['preset'], p.get('hint') or None, pol, allow, tracker(job, report)), doc_id=did)
        else: out = m.read_file(job.target, sh, 'llm', p.get('model'), p['preset'], p.get('hint', ''), p.get('pages'), pol, allow,
                                p.get('level') or None, progress=tracker(job, report))
        report(progress=.97, current='gathering the verses')
        b = m.set_book(out['doc_id'], out.get('shelf') or sh, p['preset'], p.get('counts'))
        return result(out, p) | dict(doc_id=b['doc'], title=b['title'], shelf=out.get('shelf') or p.get('shelf') or '', chapters=len(b['chapters']),
                                     verses=b['verses'], problems=sum(r['state'] == 'open' for r in b['probs']))
    ctx.jobs.register('read', read_job)
    ctx.jobs.register('book', book_job)
    ctx.jobs.register('reparse', reparse_job)
    ctx.jobs.register('proof', proof_job)
    ctx.jobs.register('extract', extract_job)
    try: ctx.jobs.recover()
    except Exception: pass
    ctx.jobs.sweep()
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
        "A failed job runs again; a cancelled page job resumes on the pages it left unread, which are 0-based already, and a clip on the files it had not clipped."
        try:
            j = ctx.jobs.get(jid)
            if j.status == 'cancelled' and j.kind not in CLIPS and (r := j.result or {}).get('unread'):
                ctx.jobs.update(jid, params=dict(j.params, pages=r['unread'], **{'resume': r['doc_id']} if j.kind in ('read', 'book') and r.get('doc_id') else {}))
            return job_card(ctx.jobs.launch(jid))
        except Exception as e: return fail(e)
    @rt('/jobs/{jid}/cancel')
    def job_cancel(jid: str):
        try: return job_card(ctx.jobs.cancel(jid))
        except Exception as e: return fail(e, kind='bad_request')
    @rt('/clip')
    def clip(target: str, kind: str = 'clip', shelf: str = '', origin: str = ''):
        try:
            if kind not in ('clip', 'clip_tree', 'clip_codebase', 'clip_api_spec'):
                raise ValueError(f'unknown clip kind {kind!r}')
            cancel = {'_cancel': True} if kind in CLIPS else {}
            from vishalakshi.read import IMG_EXTS
            p = Path(target).expanduser()
            # page by page, so a scan gets routes and flags; no model, so nothing leaves before a person says where it may go
            if kind == 'clip' and p.is_file() and p.suffix.lower() in ('.pdf', *IMG_EXTS):
                c = ctx.session.vault_read.get(str(p.resolve().parent)) or {}
                return job_card(ctx.jobs.start('read', str(p.resolve()), _cancel=True, shelf=shelf or None, parse=c.get('parse', 'auto'),
                                               preset=c.get('preset', 'generic'), hint=c.get('hint', '')))
            return job_card(ctx.jobs.start(kind, target, shelf=shelf or None, **cancel, **{'from': origin} if origin else {}))
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
    @rt('/vault/watch', methods=['POST'])
    async def watch(target: str, action: str = 'url', every: str = '1d', note: str = '', shelf: str = ''):
        try:
            if not target.strip(): raise ValueError('nothing to watch')
            await off_loop(lambda: ctx.memory.watch(target, action=action, every=every,
                note=note or None, shelf=shelf or None))
            return ui.watch_list(ctx.memory.watches(shelf=shelf or None))
        except Exception as e: return fail(e)
    @rt('/vault/unwatch', methods=['POST'])
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
    @rt('/learn/import', methods=['GET'])
    def learn_import_offer(again: bool = False):
        if not (o := _offer(ctx.vaults, again)): return ui.learn_result({'ok': True, 'choice': 'none'}) if again else Response(status_code=204)
        return ui.learn_offer(*o)
    @rt('/vault/learn-import', methods=['GET', 'POST'])
    async def learn_import(req: Request, choice: str = ''):
        src, ref = _standalone_vault(), ctx.vaults.get(LEARN)
        if req.method == 'GET': return {'found': src is not None, 'source': str(src) if src else None, 'learn_exists': ref is not None}
        try: out = _do_learn_import(ctx, src, ref, choice)
        except Exception as e: out = _refusal(e)
        if req.headers.get('hx-request') != 'true': return out
        body = json.loads(out.body) if isinstance(out, Response) else out
        return ui.learn_result(body)
    @rt('/vault/attach')
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
            if wb:
                view = getattr(first(t for t in ctx.session.tabs if t.kind == 'vaultwb'), 'ref', '') or 'library'
                return ui.workbench(_mem(ref.name), ctx.vaults, view, body=_view(view, ref.name))
            return dict(ref.dict(), note=ctx.vaults.note)
        except Exception as e: return fail(e)
    @rt('/vault/access')
    async def vault_access(name: str = '', access: str = '', agent: str = '', privacy: str = ''):
        "Who may write a vault, whether the model may, and its privacy floor: the level no document in it goes below."
        try:
            if access: ctx.vaults.set_access(name, access)
            if agent: ctx.vaults.set_agent(name, agent.lower() in ('1', 'true', 'yes', 'on'))
            ref = ctx.vaults.get(name or None)
            if ref is None: raise VaultRefused(f'no vault {name}', 'not_found', 404)
            m = ctx.vaults.memory(ref.name)
            if privacy:
                _check('auto', 'generic', privacy)
                _writable(ref.name)
                await off_loop(m.set_floor, privacy, 'person')
            return dict(ref.dict(), floor=await off_loop(m.floor), note=ctx.vaults.note, ok=True)
        except Exception as e: return _refusal(e)
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
            if not row: return fail('no such document', 404, kind='not_found')
            privacy = await off_loop(m.pii, doc, shelf or None)
            evidence = await off_loop(m.pii_evidence, doc, shelf or None) if privacy.get('has_pii') else []
            pages = await off_loop(m.pages, row.get('id') or doc, shelf or None)
            return {'doc': row, 'shelf': shelf, 'sections': await off_loop(m.sections, doc, shelf or None),
                    'privacy': privacy, 'evidence': evidence, 'covers': PII_COVERS, 'note': m.note,
                    'level': _plain(await off_loop(m.level, row.get('id') or doc, shelf or None)), 'paged': len(pages),
                    'writable': bool(getattr(ctx.vaults.get(vault or None), 'writable', False))}
        except Exception as e: return _refusal(e)
    def _model(model):
        "The reader for a model name, and the name kept for the line."
        return dict(model=reader_id(model), name=model) if model else dict(model=None, name='')
    def _plan(m, src, shelf, parse, model, pages, level, allow):
        r = _model(model)
        return m.read_plan(src, shelf or None, parse, r['model'], page_list(pages), ctx.session.vault_pii, allow, level or None, r['name'])
    def _check(parse, preset, level):
        from vishalakshi.read import PARSE, PRESETS
        from vishalakshi.pii import LEVELS
        if parse not in PARSE: raise VaultRefused(f'parse is one of {", ".join(PARSE)}', 'bad_request')
        if preset not in PRESETS: raise VaultRefused(f'preset is one of {", ".join(PRESETS)}', 'bad_request')
        if level and level not in LEVELS: raise VaultRefused(f'level is one of {", ".join(LEVELS)}', 'bad_request')
    @rt('/vault/read')
    async def vault_read(src: str = '', parse: str = 'auto', preset: str = 'generic', model: str = '', hint: str = '',
                         pages: str = '', level: str = '', allow: bool = False, partial: bool = False,
                         estimate: bool = False, vault: str = '', shelf: str = ''):
        "The Read sheet: `estimate` says what a read would do and send; otherwise the read starts as a job."
        try:
            _check(parse, preset, level)
            m = _mem(vault)
            if not src.strip(): raise VaultRefused('nothing to read', 'bad_request')
            folder = str(Path(src).expanduser().resolve().parent)
            if estimate:
                # an estimate with a model nobody has yet still says what the pages are
                try: plan = await off_loop(_plan, m, src, shelf, parse, model, pages, level, allow)
                except VaultRefused as e:
                    if e.kind != 'model_unavailable': raise
                    plan = dict(await off_loop(_plan, m, src, shelf, parse, '', pages, level, allow), ok=False, kind=e.kind, why=str(e))
                from vishalakshi.read import PARSE, PRESETS
                return dict(_plain(plan), ok=True, check_ok=plan['ok'], remembered=ctx.session.vault_read.get(folder),
                            parses=list(PARSE), presets=list(PRESETS), vault=vault or ctx.vaults.active.name)
            _writable(vault)
            if parse == 'llm' and not model: raise VaultRefused('reading every page by model needs a model', 'model_unavailable')
            plan = await off_loop(_plan, m, src, shelf, parse, model, pages, level, allow)
            if busy := _src_busy(plan.src, plan.doc):
                raise VaultRefused(f'{Path(plan.src).name} is already being read', 'busy', 409, job=busy.id)
            if not plan.ok and not partial:
                raise VaultRefused(plan.why, plan.kind, 400, pages=[w['page'] for w in plan.withheld], line=plan.why)
            r = _model(model)
            ctx.session.vault_read[folder] = read_choice(dict(parse=parse, preset=preset, model=model, hint=hint))
            ctx.session.save()
            return job_card(ctx.jobs.start('read', plan.src, _cancel=True, vault=vault, shelf=shelf or None, parse=parse, preset=preset,
                                           model=r['model'], name=r['name'], hint=hint, pages=page_list(pages),
                                           level=level or None, allow=bool(allow)))
        except Exception as e: return _refusal(e)
    def _turn_name():
        "The conversation's model, which a send with no model named goes to."
        try: return ctx.session.ai.model.name
        except Exception: return ''
    def _ask_policy(spec):
        "What Find > Ask applies: a local model reads whole, a hosted one masks or withholds; a stored `off` does not apply to ask."
        if spec.local: return dict(pii='local', pii_model=spec.name), 'redact'
        p = ctx.session.vault_pii if ctx.session.vault_pii in ('redact', 'refuse') else 'redact'
        return dict(pii=p, pii_model=None), p
    def _line(chk):
        return dict(_plain({k: chk.get(k) for k in ('ok', 'kind', 'kinds', 'why', 'local', 'send', 'masked', 'withheld')}), ok=True, check_ok=chk.ok)
    @rt('/vault/send-check')
    async def vault_send_check(refs: str = '', src: str = '', parse: str = 'auto', model: str = '', pages: str = '',
                               level: str = '', allow: bool = False, vault: str = '', shelf: str = '', doc: str = '',
                               ask: bool = False, attach: str = ''):
        """Where a send goes and what of it goes how: one answer for every send line. `doc` checks page images of a read document for
        each reader in `model`; `ask` the sections an answer may draw on; `attach` (JSON) the prompt bar's attachments for the turn model."""
        try:
            _check(parse, 'generic', level)
            m = _mem(vault)
            if attach.strip():
                atts = json.loads(attach)
                if not isinstance(atts, list): raise VaultRefused('attach is a JSON list', 'bad_request')
                spec = chat_spec(model) if model else ctx.session.ai.model
                chk = await off_loop(ctx.session.attachment_check, atts, spec)
                return dict(_plain(chk), ok=True, check_ok=chk.ok)
            if ask:
                spec = chat_spec(model or _turn_name())
                chk = await off_loop(m.ask_check, doc or None, shelf or None, page_list(pages), spec.local, spec.name, _ask_policy(spec)[1])
                return _line(chk)
            if doc.strip():
                chk = await off_loop(_pages_check, m, doc, shelf, pages, model, allow)
                return dict(_plain(chk), ok=True, check_ok=chk.ok)
            if src.strip():
                plan = await off_loop(_plan, m, src, shelf, parse, model, pages, level, allow)
                return dict(_plain(plan), ok=True, check_ok=plan.ok)
            ids = [x for x in refs.split(',') if x.strip()]
            if not ids: raise VaultRefused('nothing to check', 'bad_request')
            spec = chat_spec(model or _turn_name())
            pol = 'off' if spec.local else ctx.session.vault_pii
            return _line(await off_loop(m.check, ids, (), shelf or None, spec.local, spec.name, pol, False, allow))
        except json.JSONDecodeError: return _refusal(VaultRefused('attach is a JSON list', 'bad_request'))
        except Exception as e: return _refusal(e)
    @rt('/vault/ask')
    async def vault_ask(q: str = '', doc: str = '', pages: str = '', model: str = '', vault: str = '', shelf: str = ''):
        "A cited answer from the whole vault, one document or pages of it, streamed: `send`, `reset`/`chunk` as it is written, `answer`, `done`."
        try:
            if not q.strip(): raise VaultRefused('nothing to ask', 'bad_request')
            m, pg = _mem(vault), page_list(pages)
            spec = chat_spec(model or _turn_name())
            pol, line_pol = _ask_policy(spec)
            chk = await off_loop(m.ask_check, doc or None, shelf or None, pg, spec.local, spec.name, line_pol)
        except Exception as e: return _refusal(e)
        from starlette.responses import StreamingResponse
        from vishalakshi.pii import redact
        loop, qu = asyncio.get_running_loop(), asyncio.Queue()
        # the answer is scrubbed once whole; until then what streams is masked whenever the scope holds anything not Open
        hide = any(r.level != 'open' for r in chk.rows)
        def put(ev, d):
            if ev == 'chunk': d = dict(text=redact(d, ner=True) if hide else d)
            loop.call_soon_threadsafe(qu.put_nowait, (ev, d))
        def run():
            try: put('answer', _plain(m.ask(q, doc or None, shelf or None, pg, spec.name, lambda *a, **kw: Streamed(ask_chat(spec)(*a, **kw), put), **pol)))
            except Exception as e: put('error', dict(error=errstr(e), kind=getattr(e, 'kind', None) or 'failed'))
            finally: put('end', None)
        async def events():
            yield sse('send', dict(why=chk.why, kind=chk.kind, check_ok=chk.ok, model=spec.name, local=spec.local))
            task = asyncio.ensure_future(off_loop(run))
            while (got := await qu.get())[0] != 'end': yield sse(*got)
            await task
            yield sse('done', {})
        return StreamingResponse(events(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
    @rt('/vault/types')
    async def vault_types(state: str = 'proposed', vault: str = '', shelf: str = ''):
        "Documents whose type is a guess waiting on a person, and the labels a person may pick instead."
        try:
            if state != 'proposed': raise VaultRefused('state is proposed', 'bad_request')
            from varga import DOCTYPES
            return {'ok': True, 'types': _plain(await off_loop(_mem(vault).types, shelf or None)), 'labels': sorted(DOCTYPES) + ['other']}
        except Exception as e: return _refusal(e)
    @rt('/vault/types/guess')
    async def vault_types_guess(vault: str = '', shelf: str = ''):
        "Type every untyped document from its cues; no model is asked."
        try:
            _writable(vault)
            return {'ok': True} | await off_loop(_mem(vault).guess_types, shelf or None)
        except Exception as e: return _refusal(e)
    @rt('/vault/types/{verdict}')
    async def vault_types_judge(verdict: str, doc: str = '', doctype: str = '', was: str = '', vault: str = '', shelf: str = ''):
        "`accept` a proposed type, or `doctype` instead; `reject` it; `undo` back to `was` (JSON), which the other two answered."
        try:
            if verdict not in ('accept', 'reject', 'undo'): raise VaultRefused('accept, reject or undo', 'not_found', 404)
            _writable(vault)
            w = json.loads(was) if was.strip() else None
            return {'ok': True} | _plain(await off_loop(_mem(vault).judge_type, doc, verdict, shelf or None, doctype or None, w))
        except json.JSONDecodeError: return _refusal(VaultRefused('was is a JSON object', 'bad_request'))
        except Exception as e: return _refusal(e)
    @rt('/vault/fields')
    async def vault_fields(doc: str = '', vault: str = '', shelf: str = ''):
        "Each extracted field with its page, quote and warnings."
        try: return {'ok': True} | _plain(await off_loop(_mem(vault).fields, doc, shelf or None))
        except Exception as e: return _refusal(e)
    @rt('/vault/extract')
    async def vault_extract(doc: str = '', model: str = '', vault: str = '', shelf: str = ''):
        "Read the fields again as a job, after the same check the send line shows."
        try:
            m = _mem(vault)
            _writable(vault)
            did = await off_loop(m.doc_id, doc, shelf or None)
            _busy(m, did, shelf or None)
            spec = chat_spec(model or _turn_name())
            pol = 'off' if spec.local else ctx.session.vault_pii
            chk = await off_loop(m.check, [did], (), shelf or None, spec.local, spec.name, pol)
            if not chk.ok: raise VaultRefused(chk.why, chk.kind, 400, line=chk.why)
            title = (await off_loop(m.document, did, shelf or None)).get('title') or ''
            return job_card(ctx.jobs.start('extract', did, vault=vault, shelf=shelf or None, model=spec.model_id,
                                           chat_kw={'runtime': spec.runtime}, name=spec.name, pii=pol, title=title))
        except Exception as e: return _refusal(e)
    @rt('/vault/pages')
    async def vault_pages(doc: str, vault: str = '', shelf: str = '', history: bool = False):
        try:
            m = _mem(vault)
            row = await off_loop(m.document, doc, shelf or None)
            if not row: raise VaultRefused(f'no document {doc}', 'not_found', 404)
            return {'ok': True, 'doc': doc, 'source': row.get('source'), 'kind': row.get('kind'),
                    'pages': _plain(await off_loop(m.pages, doc, shelf or None, history))}
        except Exception as e: return _refusal(e)
    @rt('/vault/page')
    async def vault_page(doc: str, page: int = 0, version: int = 0, view: str = '', vault: str = '', shelf: str = ''):
        "One page; `view=sent` is its text as a hosted model receives it."
        try:
            m = _mem(vault)
            if view == 'sent': return dict(_plain(await off_loop(m.as_sent, doc, page, shelf or None, ctx.session.vault_pii)), ok=True, view='sent')
            return dict(_plain(await off_loop(m.page, doc, page, shelf or None, version or None)), ok=True)
        except Exception as e: return _refusal(e)
    @rt('/vault/page/diff')
    async def vault_page_diff(doc: str, page: int = 0, a: int = 0, b: int = 0, vault: str = '', shelf: str = ''):
        try:
            if a < 1 or b < 1: raise VaultRefused('a and b are versions, from 1', 'bad_request')
            return dict(await off_loop(_mem(vault).page_diff, doc, page, a, b, shelf or None), ok=True)
        except Exception as e: return _refusal(e)
    @rt('/vault/page/crop')
    async def vault_page_crop(doc: str, page: int = 0, box: str = '', vault: str = '', shelf: str = ''):
        try:
            bx = [float(x) for x in box.split(',')] if box.strip() else None
            b, mime = await off_loop(_mem(vault).page_crop, doc, page, bx, shelf or None)
            return Response(b, media_type=mime, headers={'Cache-Control': 'private, max-age=600'})
        except ValueError as e: return _refusal(VaultRefused(f'box is x0,y0,x1,y1 ({errstr(e)})', 'bad_request'))
        except Exception as e: return _refusal(e)
    def _readers(names):
        "`(id, name)` for each model name, `model_unavailable` for one that cannot read page images."
        rs = [(reader_id(n), n) for n in dict.fromkeys(x.strip() for x in str(names or '').split(',') if x.strip())]
        if not rs: raise VaultRefused('choose a model to read the pages', 'model_unavailable')
        return rs
    def _pages_check(m, doc, shelf, pages, names, allow):
        return m.page_check(doc, page_list(pages), _readers(names), shelf or None, ctx.session.vault_pii, allow)
    PAGED = ('read', 'reparse', 'proof', 'extract', 'book')
    def _src_busy(*targets):
        "The job running on the file or the document `targets` name, if one is."
        return first(j for j in ctx.jobs.all(limit=100) if j.active and j.kind in PAGED and j.target in [t for t in targets if t])
    def _busy(m, doc, shelf):
        "`busy` while a read, a re-read, a proofread or a book runs on `doc`: a decision now would land on a page about to change."
        if j := _src_busy(doc, str(m.document(doc, shelf).get('source') or '')):
            raise VaultRefused(f'a {j.kind} job is running on this document', 'busy', 409, job=j.id)
    def _folder(m, doc, shelf):
        src = Path(str(m.document(doc, shelf).get('source') or ''))
        return str(src.parent) if src.is_absolute() else ''
    async def _page_job(kind, doc, pages, names, allow, partial, vault, shelf, **kw):
        "The guards a re-read and a proofread share, then the job."
        m = _mem(vault)
        _writable(vault)
        row = await off_loop(m.document, doc, shelf or None)
        if not row: raise VaultRefused(f'no document {doc}', 'not_found', 404)
        _busy(m, doc, shelf or None)
        rs = _readers(names)
        chk = await off_loop(lambda: m.page_check(doc, page_list(pages), rs, shelf or None, ctx.session.vault_pii, allow))
        if not chk.ok and not partial: raise VaultRefused(chk.why, chk.kind, 400, pages=chk.withheld, line=chk.why)
        return job_card(ctx.jobs.start(kind, doc, _cancel=True, vault=vault, shelf=shelf or None, pages=page_list(pages),
                                       title=row.get('title') or '', allow=bool(allow), **kw))
    @rt('/vault/reparse')
    async def vault_reparse(doc: str, pages: str = '', model: str = '', preset: str = '', hint: str = '', allow: bool = False,
                            partial: bool = False, vault: str = '', shelf: str = ''):
        "Read pages of a read document again with another model or preset, as a job; each page gets a new version."
        try:
            if preset: _check('auto', preset, '')
            if ',' in model: raise VaultRefused('a re-read takes one model', 'bad_request')
            r = _model(model)
            if not r['model']: raise VaultRefused('a re-read needs a model', 'model_unavailable')
            return await _page_job('reparse', doc, pages, model, allow, partial, vault, shelf,
                                   model=r['model'], name=model, preset=preset or None, hint=hint or None)
        except Exception as e: return _refusal(e)
    @rt('/vault/proofread')
    async def vault_proofread(doc: str, readers: str = '', pages: str = '', agree: int = 0, allow: bool = False, partial: bool = False,
                              estimate: bool = False, vault: str = '', shelf: str = ''):
        "Readers read the pages again and their word changes are filed for review. `estimate` says where each reader's pages would go."
        try:
            m = _mem(vault)
            folder = await off_loop(_folder, m, doc, shelf or None)
            mem = ctx.session.vault_read.get(folder) or {}
            if estimate:
                out = dict(ok=True, remembered={k: mem[k] for k in ('readers', 'agree') if k in mem}, pages=len(await off_loop(m.pages, doc, shelf or None)))
                if not readers.strip(): return out
                chk = await off_loop(_pages_check, m, doc, shelf, pages, readers, allow)
                return out | _plain(chk) | dict(ok=True, check_ok=chk.ok)
            rs = _readers(readers)
            n = max(1, min(len(rs), agree or mem.get('agree') or 2))
            out = await _page_job('proof', doc, pages, readers, allow, partial, vault, shelf, readers=[i for i, _ in rs], agree=n,
                                  name=', '.join(nm for _, nm in rs))
            if folder:
                ctx.session.vault_read[folder] = read_choice(dict(mem, readers=[nm for _, nm in rs], agree=n))
                ctx.session.save()
            return out
        except Exception as e: return _refusal(e)
    @rt('/vault/changes')
    async def vault_changes(doc: str = '', state: str = '', page: int = -1, vault: str = '', shelf: str = ''):
        "Proofreading changes still to decide, across every paged document or for one."
        try:
            if state and state not in ('proposed', 'doubt', 'accepted', 'rejected'): raise VaultRefused('state is proposed, doubt, accepted or rejected', 'bad_request')
            rows = await off_loop(_mem(vault).changes, doc or None, shelf or None, state or None, None if page < 0 else page)
            return {'ok': True, 'changes': _plain(rows)}
        except Exception as e: return _refusal(e)
    def _ids(ids): return [x for x in str(ids or '').split(',') if x.strip()]
    async def _decide(f, doc, vault, shelf, *a):
        m = _mem(vault)
        _writable(vault)
        _busy(m, doc, shelf or None)
        return {'ok': True} | _plain(await off_loop(f, m, *a))
    @rt('/vault/changes/accept')
    async def vault_changes_accept(doc: str, ids: str = '', after: str = None, edits: str = '', vault: str = '', shelf: str = ''):
        "Apply changes, one new version per page; `after` or `edits` (JSON `{id: after}`) edit them first. `stale` with the ids that cannot be."
        try:
            ed = json.loads(edits) if edits.strip() else None
            if ed is not None and not isinstance(ed, dict): raise VaultRefused('edits is a JSON object of id to text', 'bad_request')
            return await _decide(lambda m: m.accept_changes(doc, _ids(ids), shelf or None, after, ed), doc, vault, shelf)
        except Exception as e: return _refusal(e)
    @rt('/vault/changes/reject')
    async def vault_changes_reject(doc: str, ids: str = '', vault: str = '', shelf: str = ''):
        try: return await _decide(lambda m: m.reject_changes(doc, _ids(ids), shelf or None), doc, vault, shelf)
        except Exception as e: return _refusal(e)
    @rt('/vault/changes/undo')
    async def vault_changes_undo(doc: str, ids: str = '', vault: str = '', shelf: str = ''):
        "Undo the last decision: a reject goes back to the queue, an accept is reverted as a new version and its changes are open again."
        try: return await _decide(lambda m: m.undo_changes(doc, _ids(ids), shelf or None), doc, vault, shelf)
        except Exception as e: return _refusal(e)
    @rt('/vault/page/revert')
    async def vault_page_revert(doc: str, page: int = 0, version: int = 0, vault: str = '', shelf: str = ''):
        "File an old version of a page as its newest; the history stays."
        try:
            if version < 1: raise VaultRefused('version is a number from 1', 'bad_request')
            return await _decide(lambda m: m.revert_page(doc, page, version, shelf or None), doc, vault, shelf)
        except Exception as e: return _refusal(e)
    @rt('/vault/book')
    async def vault_book(req, src: str = '', doc: str = '', preset: str = 'sanskrit', model: str = '', hint: str = '', pages: str = '',
                         counts: str = '', level: str = '', allow: bool = False, partial: bool = False, vault: str = '', shelf: str = ''):
        "A GET is the book a document's pages make now. A POST reads a file, or a filed document again, by model as a book of verses: a job."
        try:
            m = _mem(vault)
            if req.method != 'POST': return {'ok': True} | _plain(await off_loop(m.book, doc, shelf or None))
            if preset not in VERSE_SCRIPT: raise VaultRefused(f'a book of verses is read with {" or ".join(VERSE_SCRIPT)}', 'bad_request')
            _check('llm', preset, level)
            cs, r = counts_list(counts), _model(model)
            if not r['model']: raise VaultRefused('a book is read page by page by a model: choose one', 'model_unavailable')
            kw = dict(model=r['model'], name=model, preset=preset, hint=hint, counts=cs)
            if not doc and src.strip():
                plan = await off_loop(_plan, m, src, shelf, 'llm', model, pages, level, allow)
                if plan.doc: doc = plan.doc     # read before: read again, so its history and decisions stay
                else:
                    _writable(vault)
                    if busy := _src_busy(plan.src): raise VaultRefused(f'{Path(plan.src).name} is already being read', 'busy', 409, job=busy.id)
                    if not plan.ok and not partial: raise VaultRefused(plan.why, plan.kind, 400, pages=[w['page'] for w in plan.withheld], line=plan.why)
                    ctx.session.vault_read[str(Path(plan.src).parent)] = read_choice(dict(parse='llm', preset=preset, model=model, hint=hint, book=True))
                    ctx.session.save()
                    return job_card(ctx.jobs.start('book', plan.src, _cancel=True, vault=vault, shelf=shelf or None, pages=page_list(pages),
                                                   level=level or None, allow=bool(allow), **kw))
            if not doc: raise VaultRefused('nothing to read', 'bad_request')
            return await _page_job('book', doc, pages, model, allow, partial, vault, shelf, again=True, **kw)
        except Exception as e: return _refusal(e)
    @rt('/vault/book/problems')
    async def vault_book_problems(doc: str = '', state: str = 'open', vault: str = '', shelf: str = ''):
        "A book's problems in `state`, or every book's."
        try:
            if state not in ('open', 'checked', 'dismissed', ''): raise VaultRefused('state is open, checked or dismissed', 'bad_request')
            return {'ok': True, 'problems': _plain(await off_loop(_mem(vault).book_problems, doc or None, shelf or None, state))}
        except Exception as e: return _refusal(e)
    @rt('/vault/book/probs/{verdict}')
    async def vault_book_judge(verdict: str, doc: str = '', ids: str = '', vault: str = '', shelf: str = ''):
        "`accept` a problem as checked, `reject` it as none, `undo` either."
        try:
            if verdict not in ('accept', 'reject', 'undo'): raise VaultRefused('accept, reject or undo', 'not_found', 404)
            _writable(vault)
            return {'ok': True} | _plain(await off_loop(_mem(vault).judge_probs, doc, _ids(ids), verdict, shelf or None))
        except Exception as e: return _refusal(e)
    @rt('/vault/book.md')
    async def vault_book_md(req, doc: str = '', vault: str = '', shelf: str = ''):
        "The book as markdown: a GET downloads it, a POST writes it beside the source file."
        try:
            m = _mem(vault)
            if req.method == 'POST':
                _writable(vault)
                return {'ok': True, 'path': await off_loop(m.save_book_md, doc, shelf or None)}
            return Response(await off_loop(m.book_md, doc, shelf or None), media_type='text/markdown; charset=utf-8',
                            headers={'Content-Disposition': 'attachment; filename="BOOK.md"'})
        except Exception as e: return _refusal(e)
    @rt('/vault/sends')
    async def vault_sends(doc: str = '', vault: str = '', shelf: str = '', limit: int = 100):
        "What left this machine, for which model, under which policy: one document's, or the vault's."
        try: return {'ok': True, 'sends': _plain(await off_loop(_mem(vault).sends, doc or None, shelf or None, max(1, min(1000, limit))))}
        except Exception as e: return _refusal(e)
    @rt('/vault/proof.md')
    async def vault_proof_md(req, doc: str, vault: str = '', shelf: str = ''):
        "The proofreading record as PROOFREAD.md: a GET downloads it, a POST writes it beside the source file."
        try:
            m = _mem(vault)
            if req.method == 'POST':
                _writable(vault)
                return {'ok': True, 'path': await off_loop(m.save_proof_md, doc, shelf or None)}
            md = await off_loop(m.proof_md, doc, shelf or None)
            return Response(md, media_type='text/markdown; charset=utf-8', headers={'Content-Disposition': 'attachment; filename="PROOFREAD.md"'})
        except Exception as e: return _refusal(e)
    @rt('/vault/pii/findings')
    async def vault_findings(doc: str = '', state: str = '', page: int = -1, vault: str = '', shelf: str = ''):
        "Filed personal information, masked previews only, across every paged document or for one."
        try:
            if state and state not in ('found', 'accepted', 'rejected'): raise VaultRefused('state is found, accepted or rejected', 'bad_request')
            rows = await off_loop(_mem(vault).findings, doc or None, shelf or None, state or None, None if page < 0 else page)
            return {'ok': True, 'findings': _plain(rows)}
        except Exception as e: return _refusal(e)
    @rt('/vault/pii/findings/{verdict}')
    async def vault_findings_judge(verdict: str, doc: str, ids: str = '', vault: str = '', shelf: str = ''):
        "`accept` is personal, `reject` is not personal, `undo` hands it back to detection. `stale` when the page was read again."
        try:
            if verdict not in ('accept', 'reject', 'undo'): raise VaultRefused('accept, reject or undo', 'not_found', 404)
            return await _decide(lambda m: m.judge_pii(doc, _ids(ids), verdict, shelf or None), doc, vault, shelf)
        except Exception as e: return _refusal(e)
    @rt('/vault/pii/scan')
    async def vault_pii_scan(doc: str, vault: str = '', shelf: str = ''):
        "File findings for a document read before findings were kept."
        try: return await _decide(lambda m: m.scan_pii(doc, shelf or None), doc, vault, shelf)
        except Exception as e: return _refusal(e)
    @rt('/vault/page/img')
    async def vault_page_img(doc: str, page: int = 0, w: int = 0, vault: str = '', shelf: str = ''):
        try:
            b, mime = await off_loop(_mem(vault).page_image, doc, page, shelf or None, w)
            return Response(b, media_type=mime, headers={'Cache-Control': 'private, max-age=600'})
        except Exception as e: return _refusal(e)
    @rt('/vault/privacy')
    async def vault_privacy(req, doc: str, level: str = '', reason: str = '', vault: str = '', shelf: str = ''):
        "A document's level; a POST is a person setting it, or handing it back to detection with an empty one."
        try:
            if req.method != 'POST': return dict(_plain(await off_loop(_mem(vault).level, doc, shelf or None)), ok=True)
            _check('auto', 'generic', level)
            _writable(vault)
            return {'ok': True, 'privacy': _plain(await off_loop(_mem(vault).set_level, doc, level or None, shelf or None, reason))}
        except Exception as e: return _refusal(e)
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
    @rt('/vault/shelf/move', methods=['POST'])
    async def vault_move(doc: str, target: str, vault: str = '', shelf: str = ''):
        try:
            _writable(vault)
            return await off_loop(_mem(vault).move, doc, target, shelf or None)
        except Exception as e: return _refused(e)
    @rt('/vault/shelf/drop', methods=['POST'])
    async def vault_drop_shelf(shelf: str, vault: str = ''):
        try:
            _writable(vault)
            return await off_loop(_mem(vault).drop_shelf, shelf)
        except Exception as e: return _refused(e)
    @rt('/vault/not-pii', methods=['POST'])
    async def vault_not_pii(doc: str, vault: str = '', shelf: str = '', clear: bool = True, reason: str = ''):
        try:
            _writable(vault)
            m = _mem(vault)
            await off_loop(m.mark_not_pii, doc, shelf or None, clear, reason)
            return {'ok': True, 'privacy': await off_loop(m.pii, doc, shelf or None), 'covers': PII_COVERS}
        except Exception as e: return _refused(e)
    @rt('/vault/pii/mark', methods=['POST'])
    async def vault_mark_pii(doc: str, vault: str = '', shelf: str = '', force: bool = True, reason: str = ''):
        "The override the arithmetic cannot reach: a name, an address, a whole scanned page."
        try:
            _writable(vault)
            m = _mem(vault)
            await off_loop(m.mark_pii, doc, shelf or None, force, reason)
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
            return Div(*([Button(f"{f['name']} · {round(f['bytes'] / 1024)}kb", cls='lee-btn',
                                 title=f['path'], hx_post='/vault/attach', hx_target='#vaultpanel',
                                 hx_swap='none', hx_vals=json.dumps({'path': f['path'], 'name': f['name']}), **ui.SETTLED)
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
                        src: str = '', match: str = '', feed: str = '', name: str = '', doc: str = '', title: str = '',
                        pages: str = '', scope: str = '', mode: str = ''):
        try:
            body = await off_loop(_view, view, vault, shelf, q, src, match, feed, name, doc, title, pages, scope, mode)
            ctx.session.note_vault_view(view)
            return ui.workbench(_mem(vault), ctx.vaults, view, body=body)
        except Exception as e: return fail(e)
    def _view(view, vault='', shelf='', q='', src='', match='', feed='', name='', doc='', title='', pages='', scope='', mode=''):
        m = _mem(vault)
        if view == 'review': return ui.review_view(vault, doc, shelf, mode)
        if view == 'find': return ui.find_view(m, vault, q=q, shelf=shelf, doc=doc, title=title, pages=pages, scope=scope)
        if view in ('news', 'sources'): return ui.sources_view(ui.news_view(m, vault, feeds=ctx.feeds, q=q, feed=feed), 'news', vault)
        if view == 'specs': return ui.sources_view(ui.specs_view(m, vault, **_spec_kw(src, match, name)), 'specs', vault)
        if view == 'topics': return ui.sources_view(ui.topics_view(m, vault), 'topics', vault)
        if view == 'settings': return ui.vault_settings(m, vault, ctx.vaults.dict())
        return ui.library_view(m, vault, shelf=shelf, q=q, jobs=ctx.jobs, root=_root())
    def _news(vault='', **kw): return ui.sources_view(ui.news_view(_mem(vault), vault, feeds=ctx.feeds, **kw), 'news', vault)
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
                             src: str = '', match: str = '', feed: str = '', name: str = '', doc: str = '', title: str = '',
                             pages: str = '', scope: str = '', mode: str = ''):
        try:
            body = await off_loop(_view, view, vault, shelf, q, src, match, feed, name, doc, title, pages, scope, mode)
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
        "Call one operation and show what came back."
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
            # a note or a harvest is one vishalakshi call with no stop to ask
            from .clip import stoppable
            return job_card(ctx.jobs.start(kind, target, action=act, shelf=shelf or None, **{'_cancel': True} if stoppable(act) else {}))
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
        except Exception as e: return _news(vault, error=errstr(e))
        return _news(vault)
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
        except Exception as e: return _news(vault, error=errstr(e))
    @rt('/vault/news/pull')
    async def news_pull(fid: str, vault: str = ''):
        try: return await off_loop(_read_now, vault, fid)
        except Exception as e: return _news(vault, error=errstr(e))
    @rt('/vault/news/remove')
    def news_remove(fid: str, vault: str = ''):
        try:
            ctx.feeds.remove(fid)
            return _news(vault)
        except Exception as e: return _news(vault, error=errstr(e))
    @rt('/vault/news/toggle')
    def news_toggle(fid: str, enabled: bool = None, vault: str = ''):
        try:
            ctx.feeds.toggle(fid, enabled)
            return _news(vault)
        except Exception as e: return _news(vault, error=errstr(e))
    @rt('/vault/news/poll')
    def news_poll(force: bool = False):
        try: return job_card(ctx.jobs.start('feeds', force=force))
        except Exception as e: return fail(e)
    @rt('/vault/news/feeds')
    def news_feeds():
        try: return ctx.feeds.dict()
        except Exception as e: return fail(e)
