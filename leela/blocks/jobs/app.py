"""Clip, tidy and cadence routes, and the fragment that watches a job without being pushed to.

The progress loop terminates by construction: while a job is active its card carries
`hx-get`/`hx-trigger`, and the card rendered for a finished job simply does not. There is no
client-side guard to get wrong, and no socket to leak.

`jobs` is a declared capability like any other. `Jobs` is built once per workspace because it owns
threads and a SQLite file, so it lives beside the kernel pool rather than being remade per request.
"""

from __future__ import annotations

from fasthtml.common import Button, Details, Div, Form, Hidden, Input, Option, Pre, Progress, Section, Select, Span, Summary

from ...core.web import fail, off_loop

__all__ = ['CAPS', 'connect', 'job_card', 'vault_panel']

CAPS = ('fs', 'memory', 'search', 'jobs', 'tab')

POLL_MS = 1200


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
    if d['result']: body.append(Details(Summary('details'), Pre(_summarise(d['result']), cls='lee-job-result')))
    return Div(*body, cls=f"lee-job {d['status']}", id=f"job-{d['id']}", **attrs)


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


def vault_panel(memory, jobs, active_path='', root=''):
    """The clip surface: what is in the vault, what is being clipped, and what repeats.

    Server-rendered so the browser needs no state of its own -- every action is a form, and the
    job cards that come back carry their own polling.
    """
    shelves, mine = memory.shelves(), (memory.shelf_name or 'main')
    return Section(
        Div(Span('vault', cls='lee-ptitle'), Span(memory.note or '', cls='lee-keyscope'), cls='lee-phead'),
        Div(*_shelf_rows(shelves, mine), id='vaultshelves', cls='lee-vault-shelves'),
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
        Form(Button('tidy', cls='lee-btn', type='submit', title='what the vault thinks dilutes search'),
            hx_post='/vault/tidy', hx_target='#vaultjobs', hx_swap='afterbegin', cls='lee-vault-tidy'),
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
                root=str(roots[0]) if roots else '')
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

    @rt('/vault/tidy')
    def tidy(shelf: str = '', k: int = 20):
        "Candidates the vault thinks dilute retrieval, with the features that say so."
        try: return job_card(ctx.jobs.start('tidy', shelf or '', shelf=shelf or None, k=k))
        except Exception as e: return fail(e)

    @rt('/vault/noisy')
    async def mark_noisy(doc: str, shelf: str = '', noisy: bool = True, reason: str = ''):
        try: return await off_loop(lambda: ctx.memory.mark_noisy(doc, shelf=shelf or None, noisy=noisy, reason=reason))
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
