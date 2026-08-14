"""Clip, tidy and cadence routes, and the fragment that watches a job without being pushed to.

The progress loop terminates by construction: while a job is active its card carries
`hx-get`/`hx-trigger`, and the card rendered for a finished job simply does not. There is no
client-side guard to get wrong, and no socket to leak.

`jobs` is a declared capability like any other. `Jobs` is built once per workspace because it owns
threads and a SQLite file, so it lives beside the kernel pool rather than being remade per request.
"""

from __future__ import annotations

import json
from urllib.parse import urlencode

from fasthtml.common import Button, Details, Div, Form, Hidden, Input, Option, Pre, Progress, Section, Select, Span, Summary

from ... import errstr
from ..tabs.ui import tab_bar
from ...core.web import fail, off_loop
from ..memory.vaults import ACCESS

__all__ = ['CAPS', 'connect', 'job_card', 'pii_badge', 'vault_panel']

CAPS = ('fs', 'memory', 'search', 'jobs', 'tab', 'vaults')

POLL_MS = 1200

#: Said on every PII surface. The report finds *titled* names and pattern kinds, so "found" is a
#: fact and "none" never is: a bare name or an unstructured address is not looked for at all.
PII_COVERS = ('covers pattern kinds and titled names — a bare name or loose address is never '
              'looked for, so this says what was found, never that there is nothing')


def job_card(job):
    "One job, as a fragment that keeps asking until it is finished and then stops."
    d = job.dict()
    active = d['active']
    # The loop terminates by omitting these on a finished job, not by a client-side guard.
    attrs = dict(hx_get=f"/jobs/{d['id']}", hx_trigger=f'load delay:{POLL_MS}ms', hx_swap='outerHTML') if active else {}
    body = [Span(d['kind'], cls='lee-job-kind'), Span(d['status'], cls=f"lee-job-status {d['status']}"),
        Span(d['target'] or '', cls='lee-job-target', title=d['target'] or '')]
    if active:
        body.append(Progress(value=str(round(d['progress'] or 0, 3)), max='1', cls='lee-job-bar'))
        if d['current']: body.append(Span(d['current'], cls='lee-job-current'))
        body.append(Span('committed documents are searchable while this runs', cls='lee-job-note'))
    if d['error']:
        body.append(Span(d['error'], cls='lee-job-error'))
        body.append(Form(Button('retry', cls='lee-btn'), hx_post=f"/jobs/{d['id']}/retry",
            hx_target='closest .lee-job', hx_swap='outerHTML'))
    result = d['result'] if isinstance(d['result'], dict) else {}
    if pii := result.get('pii'): body.append(_clip_pii_badge(pii))
    if d['result']: body.append(Details(Summary('details'), Pre(_summarise(d['result']), cls='lee-job-result')))
    return Div(*body, cls=f"lee-job {d['status']}", id=f"job-{d['id']}", **attrs)


def _kinds(kinds):
    "`email×3, person×1` — what was found, densest first, and never more than fits on a badge."
    rows = sorted((kinds or {}).items(), key=lambda kv: -kv[1])[:4]
    return ', '.join(f'{k}×{n}' for k, n in rows)


def pii_badge(report):
    "One document's PII report as a badge. `has_pii` is the vault's, override included."
    if not report.get('doc_id') and report.get('note'): return Span('pii unavailable', cls='lee-pii', title=report['note'])
    if not report.get('has_pii'): return Span('no pattern found', cls='lee-pii clear', title=PII_COVERS)
    return Span(_kinds(report.get('kinds')), cls='lee-pii found', title=PII_COVERS)


def _clip_pii_badge(pii):
    "The same judgement over a whole clip, from the summary `clip_docs` files in its result."
    docs = pii.get('documents') or []
    if not docs: return Span('no pattern found', cls='lee-pii clear', title=PII_COVERS)
    return Span(f"pii in {len(docs)} document{'' if len(docs) == 1 else 's'} · {_kinds(pii.get('kinds'))}",
        cls='lee-pii found', title=PII_COVERS)


def _one_line(k, v):
    if isinstance(v, list):
        shown = ', '.join(map(str, v[:3])) + ('…' if len(v) > 3 else '')
        return f'{k}: {len(v)}' + (f' · {shown}' if v else '')
    if isinstance(v, dict): return f'{k}: ' + ', '.join(f'{a}={b}' for a, b in list(v.items())[:6])
    return f'{k}: {v}'


def _summarise(result, mx=40):
    "The parts of a result worth reading in a card, rather than its whole JSON."
    if not isinstance(result, dict): return str(result)[:2000]
    return '\n'.join(_one_line(k, v) for k, v in list(result.items())[:mx])


def _clip_form(target, kind, label, hint):
    "One clip action. HTMX posts it and swaps the returned card in, so no script drives this."
    return Form(Input(name='target', cls='lee-input', value=target or '', placeholder=hint, autocomplete='off'),
        Hidden(name='kind', value=kind), Button(label, cls='lee-btn go', type='submit'),
        cls='lee-clip-form', hx_post='/clip', hx_target='#vaultjobs', hx_swap='afterbegin')


def _shelf_rows(shelves, mine):
    if not shelves: return [Div('No shelf yet. Clip something and it appears here.', cls='lee-vault-empty')]
    return [Div(Span(s.get('store', ''), cls='lee-shelf-name' + (' mine' if s.get('store') == mine else '')),
        Span(f"{s.get('docs', 0)} docs", cls='lee-shelf-count'), cls='lee-shelf-row') for s in shelves]


def _watch_row(w):
    every = w.get('every') or 0
    return Div(Span(w.get('action', ''), cls='lee-watch-action'),
        Span(str(w.get('target', ''))[:60], cls='lee-watch-target', title=str(w.get('target', ''))),
        Span(f'every {round(every / 3600, 1)}h' if every else '', cls='lee-watch-every'),
        Form(Hidden(name='watch_id', value=w.get('id', '')), Button('stop', cls='lee-btn warn', type='submit'),
            hx_post='/vault/unwatch', hx_target='#vaultwatches', hx_swap='outerHTML'),
        cls='lee-watch-row')


def _watch_rows(watches):
    if not watches: return [Div('Nothing on a cadence.', cls='lee-vault-empty')]
    return [_watch_row(w) for w in watches]


def _why(row, n=3):
    "The features that put a document at this rank, strongest first, as the score's tooltip."
    feats = sorted(((k, v) for k, v in row.items() if isinstance(v, (int, float)) and k != 'score'),
        key=lambda kv: -abs(kv[1]))[:n]
    return ' · '.join(f'{k} {v:+.1f}' for k, v in feats) or 'ranked with no standout feature'


def _judge(doc, shelf, noisy, label, cls):
    "One judgement, as a form: `mark_noisy` writes to `doc_marks`, so it outlives re-ingestion."
    return Form(Hidden(name='doc', value=doc), Hidden(name='shelf', value=shelf),
        Hidden(name='noisy', value=str(noisy).lower()), Button(label, cls=cls, type='submit'),
        hx_post='/vault/noisy', hx_target='closest .lee-tidy-row', hx_swap='outerHTML')


def _pii_slot(doc, shelf=''):
    "A badge that fetches itself when its row is seen: a PII scan reads the whole document."
    return Span('scanning…', cls='lee-pii pending', hx_trigger='revealed', hx_swap='outerHTML',
        hx_get='/vault/pii/badge?' + urlencode({'doc': doc, 'shelf': shelf}))


def _tidy_row(row, shelf=''):
    "One noise candidate: what it is, why it ranks, whether it is somebody's business, and the call."
    doc = str(row.get('doc_id') or '')
    return Div(Span(row.get('title') or doc, cls='lee-tidy-title', title=doc),
        Span(f"{row.get('score') or 0:.2f}", cls='lee-tidy-score', title=_why(row)),
        _pii_slot(doc, shelf),
        _judge(doc, shelf, True, 'drop', 'lee-btn warn'), _judge(doc, shelf, False, 'keep', 'lee-btn'),
        cls='lee-tidy-row')


def _tidy_list(memory, shelf='', k=20):
    "What the vault thinks dilutes retrieval. Judged documents are already excluded from it."
    rows = memory.noisy_candidates(shelf=shelf or None, k=k)
    body = ([_tidy_row(r, shelf) for r in rows] if rows else
            [Div('Nothing looks like noise, or the shelf is too small to have an opinion.', cls='lee-vault-empty')])
    return Div(*body, id='vaulttidy', cls='lee-vault-tidyrows')


def _js(*args): return ', '.join(json.dumps(str(a or '')) for a in args)


def _doc_row(d, vault=''):
    "One document, opening the reader tab. `onclick`, because the tab is mounted by the client."
    doc, shelf = d.get('doc_id') or d.get('id'), d.get('shelf', '')
    return Div(Button(d.get('title') or doc, cls='lee-vault-doc',
            onclick=f'leeOpenVaultDoc({_js(doc, shelf, vault, d.get("title"))})'),
        Span(d.get('kind') or '', cls='lee-shelf-count'), Span(shelf, cls='lee-shelf-count'),
        cls='lee-vault-docrow')


def _hit_row(h, vault=''):
    "A search hit opens the document it is in; the breadcrumb says which part matched."
    doc, shelf = str(h.get('node_id') or '').split('#')[0], h.get('shelf', '')
    return Div(Button(h.get('breadcrumb') or h.get('title') or doc, cls='lee-vault-doc',
            onclick=f'leeOpenVaultDoc({_js(doc, shelf, vault, h.get("breadcrumb"))})'),
        Span(shelf, cls='lee-shelf-count'), cls='lee-vault-docrow')


def vault_docs(memory, q='', vault='', shelf='', limit=60):
    "The browse/search fragment: what is in the vault, or what matched."
    rows = (memory.search_all(q, limit=limit, shelves=[shelf] if shelf else None) if q.strip()
            else memory.all_documents(limit=limit, shelves=[shelf] if shelf else None))
    body = ([(_hit_row if q.strip() else _doc_row)(r, vault) for r in rows] if rows else
            [Div('Nothing here yet. Clip a document, or attach a vault.', cls='lee-vault-empty')])
    return Div(*body, id='vaultdocs', cls='lee-vault-docs')


def vault_browse(memory, q='', vault='', shelf='', limit=60):
    """The browse block: which vault is open, a search box scoped to it, and the rows.

    The form comes back with the fragment carrying the vault it was rendered for, so searching
    stays in the vault you clicked into. Were only the list swapped, the form left behind would
    still be the panel's, and the next search would silently answer from the active vault.
    """
    return Div(Span(f'documents · {vault}' if vault else 'documents', cls='lee-vault-legend'),
        Form(Hidden(name='vault', value=vault), Hidden(name='shelf', value=shelf),
            Input(name='q', value=q, cls='lee-input', placeholder='search this vault…', autocomplete='off'),
            Button('search', cls='lee-btn go', type='submit'), cls='lee-clip-form',
            hx_get='/vault/browse', hx_target='#vaultbrowse', hx_swap='outerHTML'),
        vault_docs(memory, q, vault, shelf, limit),
        id='vaultbrowse', cls='lee-vault-browse')


def _vault_row(r):
    "One vault: click the name to read it, the dot to make it active, plus who may write to it."
    name, act = r['name'], ('lee-shelf-name mine' if r['active'] else 'lee-shelf-name')
    hid = Hidden(name='name', value=name)
    # Reading a vault and writing to one are different intentions, so they are different
    # controls: the name browses without disturbing anything, and only the dot moves where
    # clips and the model's writes land.
    return Div(Button(name, cls=act + ' lee-vault-open', title=f"{r['path']} — browse this vault",
            hx_get='/vault/browse', hx_vals=json.dumps({'vault': name}),
            hx_target='#vaultbrowse', hx_swap='outerHTML'),
        Span('●', cls='lee-shelf-count lee-vault-active', title='the active vault') if r['active'] else
        Form(hid, Button('○', cls='lee-btn lee-vault-use', type='submit',
                         title='make this the active vault'),
             hx_post='/vault/activate', hx_target='#vaultpanel', hx_swap='none'),
        Form(Hidden(name='name', value=name),
             Select(*[Option(a, value=a, selected=a == r['access']) for a in ACCESS],
                    name='access', cls='lee-input', onchange='this.form.requestSubmit()'),
             hx_post='/vault/access', hx_target='closest .lee-shelf-row', hx_swap='none'),
        Form(Hidden(name='name', value=name), Hidden(name='agent', value=str(not r['agent']).lower()),
             Button('agent ' + ('on' if r['agent_writable'] else 'off'),
                    cls='lee-btn' + (' go' if r['agent_writable'] else ''), type='submit',
                    title='whether the model may write here'),
             hx_post='/vault/access', hx_target='#vaultpanel', hx_swap='none'),
        *([] if r['reserved'] else [Form(hid, Button('detach', cls='lee-btn warn', type='submit'),
             hx_post='/vault/detach', hx_target='#vaultpanel', hx_swap='none')]),
        cls='lee-shelf-row')


def vault_panel(memory, jobs, active_path='', root='', vaults=None):
    """The clip surface: what is in the vault, what is being clipped, and what repeats.

    Server-rendered so the browser needs no state of its own -- every action is a form, and the
    job cards that come back carry their own polling.
    """
    shelves, mine = memory.shelves(), (memory.shelf_name or 'main')
    return Section(
        Div(Span('vault', cls='lee-ptitle'), Span(memory.note or '', cls='lee-keyscope'), cls='lee-phead'),
        Div(Span('vaults', cls='lee-vault-legend'),
            *[_vault_row(r) for r in (vaults or {}).get('vaults', [])],
            Form(Input(name='path', cls='lee-input', placeholder='path to a vault.db, or a folder for a new one'),
                Input(name='name', cls='lee-input lee-every', placeholder='name', size='6'),
                Button('attach', cls='lee-btn', type='submit', formaction='/vault/attach'),
                Button('create', cls='lee-btn go', type='submit', formaction='/vault/create'),
                cls='lee-clip-form', hx_post='/vault/attach', hx_target='#vaultpanel', hx_swap='none'),
            cls='lee-vault-vaults'),
        Div(*_shelf_rows(shelves, mine), id='vaultshelves', cls='lee-vault-shelves'),
        # Asked for once the panel is up rather than rendered with it: the document list is a
        # query, and `vault_browse` returns the search box along with it.
        Div(id='vaultbrowse', cls='lee-vault-browse', hx_get='/vault/browse',
            hx_trigger='load', hx_swap='outerHTML'),
        Div(Span('clip', cls='lee-vault-legend'),
            _clip_form(active_path, 'clip', 'document', 'a file or folder of documents'),
            _clip_form(root, 'clip_codebase', 'codebase', 'a repository root'),
            _clip_form('', 'clip_api_spec', 'api spec', 'an OpenAPI url or path (JSON or YAML)'),
            cls='lee-vault-clip'),
        Div(Span('jobs', cls='lee-vault-legend'), *[job_card(j) for j in jobs.all(limit=8)],
            id='vaultjobs', cls='lee-vault-jobs'),
        Div(Span('cadence', cls='lee-vault-legend'),
            Form(Input(name='target', cls='lee-input', autocomplete='off', placeholder='a url to re-read, or a reminder'),
                Select(*[Option(a, value=a) for a in ('url', 'remind', 'web', 'crawl')],
                    name='action', cls='lee-input'),
                Input(name='every', cls='lee-input lee-every', value='1d', size='4'),
                Button('watch', cls='lee-btn go', type='submit'),
                cls='lee-clip-form', hx_post='/vault/watch', hx_target='#vaultwatches', hx_swap='outerHTML'),
            Div(*_watch_rows(memory.watches()), id='vaultwatches', cls='lee-vault-watches'),
            cls='lee-vault-cadence'),
        # Ranking reads every document, so the list is asked for rather than rendered with the panel.
        Div(Span('tidy', cls='lee-vault-legend'),
            Button('review', cls='lee-btn', title='what the vault thinks dilutes search',
                hx_get='/vault/tidy/list', hx_target='#vaulttidy', hx_swap='outerHTML'),
            Div(id='vaulttidy', cls='lee-vault-tidyrows'),
            cls='lee-vault-tidy'),
        cls='lee-panel lee-vault', id='vaultpanel')


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

    @rt('/jobs/{jid}/retry')
    def job_retry(jid: str):
        try: return job_card(ctx.jobs.launch(jid))
        except Exception as e: return fail(e)

    @rt('/clip')
    def clip(target: str, kind: str = 'clip', shelf: str = '', origin: str = ''):
        """Start a clip. `kind` picks the pipeline, because the three are not one shape.

        Returns as soon as the job is running: a folder of PDFs is not a request.
        """
        try:
            if kind not in ('clip', 'clip_codebase', 'clip_api_spec'): raise ValueError(f'unknown clip kind {kind!r}')
            return job_card(ctx.jobs.start(kind, target, shelf=shelf or None, **{'from': origin} if origin else {}))
        except Exception as e: return fail(e)

    @rt('/vault/panel')
    def panel():
        "The whole clip surface as one fragment. The tab's own path pre-fills the document form."
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
        "The report for one document, with what it does and does not look for."
        try:
            r = await off_loop(ctx.memory.pii, doc, shelf or None)
            return dict(r, covers='titled names and pattern kinds; a bare name is not found')
        except Exception as e: return fail(e)

    @rt('/vault/pii/badge')
    async def vault_pii_badge(doc: str, shelf: str = ''):
        "The same report as a badge. A failure is a badge too: a row must not lose its actions."
        try: return pii_badge(await off_loop(ctx.memory.pii, doc, shelf or None))
        except Exception as e: return Span('pii unavailable', cls='lee-pii', title=errstr(e))

    @rt('/vault/tidy')
    def tidy(shelf: str = '', k: int = 20):
        "The same ranking as a job, for a shelf big enough that scoring it is not a request."
        try: return job_card(ctx.jobs.start('tidy', shelf or '', shelf=shelf or None, k=k))
        except Exception as e: return fail(e)

    @rt('/vault/tidy/list')
    async def tidy_list(shelf: str = '', k: int = 20):
        "Candidates the vault thinks dilute retrieval, each with the two judgements available."
        try: return await off_loop(_tidy_list, ctx.memory, shelf, k)
        except Exception as e: return fail(e)

    @rt('/vault/noisy')
    async def mark_noisy(doc: str, shelf: str = '', noisy: bool = True, reason: str = ''):
        "Judge one candidate. The row it replaces says which way, because the list will not refetch."
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

    def _watch_list(shelf=''):
        "The cadence list, as the fragment both mutations swap themselves out for."
        return Div(*_watch_rows(ctx.memory.watches(shelf=shelf or None)), id='vaultwatches', cls='lee-vault-watches')

    @rt('/vault/watch')
    async def watch(target: str, action: str = 'url', every: str = '1d', note: str = '', shelf: str = ''):
        "Keep something fresh, or come back to it. The cadence is a vault watch row."
        try:
            if not target.strip(): raise ValueError('nothing to watch')
            await off_loop(lambda: ctx.memory.watch(target, action=action, every=every,
                note=note or None, shelf=shelf or None))
            return _watch_list(shelf)
        except Exception as e: return fail(e)

    @rt('/vault/unwatch')
    async def unwatch(watch_id: str, shelf: str = ''):
        try:
            await off_loop(ctx.memory.unwatch, watch_id, shelf or None)
            return _watch_list(shelf)
        except Exception as e: return fail(e)

    @rt('/vault/poll')
    def poll():
        "Run what is due now, rather than waiting for the tick."
        try: return job_card(ctx.jobs.start('poll'))
        except Exception as e: return fail(e)

    # -- reading a vault, rather than only writing to one ---------------------
    # These answer JSON, not fragments: the reader is a tab mounted by the client, and it needs
    # the same rows the agent gets. The panel's own surfaces above stay server-rendered forms.

    def _mem(vault=''):
        "The `Memory` for a named vault, defaulting to the active one."
        return ctx.vaults.memory(vault or None)

    def _writable(vault='', who='you'):
        "Refuse a write to a vault attached read-only, rather than doing it and reporting success."
        ref = ctx.vaults.get(vault or None)
        if ref is None: raise KeyError(vault)
        ok = ref.agent_writable if who == 'agent' else ref.writable
        if not ok: raise PermissionError(f'{ref.name} is attached read-only')
        return ref

    @rt('/vault/list')
    def vault_list():
        "Every vault leela can reach, which is active, and what may write to each."
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
    def vault_activate(name: str):
        try: return dict(ctx.vaults.activate(name).dict(), note=ctx.vaults.note)
        except Exception as e: return fail(e)

    @rt('/vault/access')
    def vault_access(name: str, access: str = '', agent: str = ''):
        "Set what a person may do here, what the model may, or both in one call."
        try:
            if access: ctx.vaults.set_access(name, access)
            if agent: ctx.vaults.set_agent(name, agent.lower() in ('1', 'true', 'yes', 'on'))
            ref = ctx.vaults.get(name)
            if ref is None: raise KeyError(name)
            return dict(ref.dict(), note=ctx.vaults.note)
        except Exception as e: return fail(e)

    @rt('/vault/documents')
    async def vault_documents(vault: str = '', shelf: str = '', kind: str = '', limit: int = 200):
        "Every document, or one shelf's, newest first. Each row says which shelf it lives in."
        try:
            m = _mem(vault)
            rows = await off_loop(m.all_documents, limit, [shelf] if shelf else None, kind or None)
            return {'documents': rows, 'shelves': m.shelves(), 'vault': ctx.vaults.get(vault or None).dict(),
                    'note': m.note}
        except Exception as e: return fail(e)

    @rt('/vault/search')
    async def vault_search(q: str, vault: str = '', shelf: str = '', limit: int = 20):
        "Search across shelves and land on sections, so a hit is somewhere you can open."
        try:
            m = _mem(vault)
            hits = await off_loop(m.search_all, q, limit, [shelf] if shelf else None)
            return {'query': q, 'hits': hits, 'note': m.note}
        except Exception as e: return fail(e)

    @rt('/vault/doc')
    async def vault_doc(doc: str, vault: str = '', shelf: str = ''):
        "One document: its row, its sections, its privacy report, and the evidence behind it."
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
        "One section's text plus what sits near it, which is what a citation has to be able to show."
        try:
            m = _mem(vault)
            sec = await off_loop(m.shelf_read, node, shelf or None)
            if not sec: return fail('no such section', 404)
            return {'section': sec, 'related': await off_loop(m.related, node, shelf or None), 'note': m.note}
        except Exception as e: return fail(e)

    def _refused(e):
        "A permission refusal is 403, so a client can tell it from a malformed request."
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
        "Override the PII report, or restore automatic detection. Written to `doc_marks`, so it lasts."
        try:
            _writable(vault)
            m = _mem(vault)
            await off_loop(m.mark_not_pii, doc, shelf or None, clear, reason)
            return {'ok': True, 'privacy': await off_loop(m.pii, doc, shelf or None), 'covers': PII_COVERS}
        except Exception as e: return _refused(e)

    @rt('/vault/open')
    def vault_open(doc: str, shelf: str = '', vault: str = '', title: str = ''):
        "Open a vault document as an editor tab, and hand the tab bar back to htmx."
        try:
            ctx.session.open_vault_doc(doc, shelf=shelf, vault=vault, title=title)
            return tab_bar(ctx.session)
        except Exception as e: return fail(e)

    @rt('/vault/browse')
    async def vault_browse_route(q: str = '', vault: str = '', shelf: str = '', limit: int = 60):
        "The document list, or the hits for a query. One fragment, swapped in either way."
        try: return await off_loop(vault_browse, _mem(vault), q, vault, shelf, limit)
        except Exception as e: return fail(e)
