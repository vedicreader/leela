"""Clip, tidy and cadence routes, and the fragment that watches a job without being pushed to.

The progress loop terminates by construction: while a job is active its card carries
`hx-get`/`hx-trigger`, and the card rendered for a finished job simply does not. There is no
client-side guard to get wrong, and no socket to leak.

`jobs` is a declared capability like any other. `Jobs` is built once per workspace because it owns
threads and a SQLite file, so it lives beside the kernel pool rather than being remade per request.
"""

from __future__ import annotations

from fasthtml.common import A, Div, Form, Progress, Span, Button, Details, Summary, Pre

from ...core.web import fail, off_loop

__all__ = ['CAPS', 'connect', 'job_card']

CAPS = ('fs', 'memory', 'search', 'jobs')

POLL_MS = 1200


def job_card(job):
    "One job, as a fragment that keeps asking until it is finished and then stops."
    d = job.dict()
    active = d['active']
    attrs = ({'hx_get': f"/jobs/{d['id']}", 'hx_trigger': f'load delay:{POLL_MS}ms',
              'hx_swap': 'outerHTML'} if active else {})
    body = [Span(d['kind'], cls='lee-job-kind'),
            Span(d['status'], cls=f"lee-job-status {d['status']}"),
            Span(d['target'] or '', cls='lee-job-target', title=d['target'] or '')]
    if active:
        body.append(Progress(value=str(round(d['progress'] or 0, 3)), max='1', cls='lee-job-bar'))
        if d['current']: body.append(Span(d['current'], cls='lee-job-current'))
        # Said plainly, because it is the reason a half-finished clip is not a failed one.
        body.append(Span('committed documents are searchable while this runs', cls='lee-job-note'))
    if d['error']:
        body.append(Span(d['error'], cls='lee-job-error'))
        body.append(Form(Button('retry', cls='lee-btn'), hx_post=f"/jobs/{d['id']}/retry",
                         hx_target='closest .lee-job', hx_swap='outerHTML'))
    if d['result']:
        body.append(Details(Summary('details'), Pre(_summarise(d['result']), cls='lee-job-result')))
    return Div(*body, cls=f"lee-job {d['status']}", id=f"job-{d['id']}", **attrs)


def _summarise(result, mx=40):
    "The parts of a result worth reading in a card, rather than its whole JSON."
    if not isinstance(result, dict): return str(result)[:2000]
    out = []
    for k, v in result.items():
        if isinstance(v, list):
            out.append(f'{k}: {len(v)}' + (f" · {', '.join(map(str, v[:3]))}…" if len(v) > 3
                                           else (f" · {', '.join(map(str, v))}" if v else '')))
        elif isinstance(v, dict): out.append(f'{k}: ' + ', '.join(f'{a}={b}' for a, b in list(v.items())[:6]))
        else: out.append(f'{k}: {v}')
        if len(out) >= mx: break
    return '\n'.join(out)


def connect(app, ctx):
    rt = app.route

    def jobs():
        "The workspace's job runner, made once and kept -- it owns threads."
        return ctx.jobs

    # A job left `running` by a killed process is a lie the moment the process dies. Done at
    # connect rather than on first request, so a reopened workspace is honest before anyone looks.
    try: ctx.jobs.recover()
    except Exception: pass

    @rt('/jobs')
    def jobs_list(kind: str = '', limit: int = 40):
        try:
            js = jobs()
            return {'jobs': [j.dict() for j in js.all(limit=limit, kind=kind or None)],
                    'note': js.note}
        except Exception as e: return fail(e)

    @rt('/jobs/{jid}')
    def job_one(jid: str):
        try: return job_card(jobs().get(jid))
        except Exception as e: return fail(e)

    @rt('/jobs/{jid}/retry')
    def job_retry(jid: str):
        try: return job_card(jobs().launch(jid))
        except Exception as e: return fail(e)

    @rt('/clip')
    def clip(target: str, kind: str = 'clip', shelf: str = '', origin: str = ''):
        """Start a clip. `kind` picks the pipeline, because the three are not one shape.

        Returns as soon as the job is running: a folder of PDFs is not a request.
        """
        try:
            if kind not in ('clip', 'clip_codebase', 'clip_api_spec'):
                raise ValueError(f'unknown clip kind {kind!r}')
            job = jobs().start(kind, target, shelf=shelf or None, **{'from': origin} if origin else {})
            return job_card(job)
        except Exception as e: return fail(e)

    @rt('/vault/shelves')
    def shelves():
        try: return {'shelves': ctx.memory.shelves(), 'note': ctx.memory.note}
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
        try: return job_card(jobs().start('tidy', shelf or '', shelf=shelf or None, k=k))
        except Exception as e: return fail(e)

    @rt('/vault/noisy')
    async def mark_noisy(doc: str, shelf: str = '', noisy: bool = True, reason: str = ''):
        try: return await off_loop(lambda: ctx.memory.mark_noisy(doc, shelf=shelf or None,
                                                                 noisy=noisy, reason=reason))
        except Exception as e: return fail(e)

    @rt('/vault/watches')
    def watches(shelf: str = '', due_only: bool = False):
        try: return {'watches': ctx.memory.watches(shelf=shelf or None, due_only=due_only),
                     'actions': ('url', 'web', 'crawl', 'arxiv', 'youtube', 'remind')}
        except Exception as e: return fail(e)

    @rt('/vault/watch')
    async def watch(target: str, action: str = 'url', every: str = '1d', note: str = '',
                    shelf: str = ''):
        "Keep something fresh, or come back to it. The cadence is a vault watch row."
        try: return await off_loop(lambda: ctx.memory.watch(target, action=action, every=every,
                                                            note=note or None, shelf=shelf or None))
        except Exception as e: return fail(e)

    @rt('/vault/unwatch')
    async def unwatch(watch_id: str, shelf: str = ''):
        try: return {'removed': await off_loop(ctx.memory.unwatch, watch_id, shelf or None)}
        except Exception as e: return fail(e)

    @rt('/vault/poll')
    def poll():
        "Run what is due now, rather than waiting for the tick."
        try: return job_card(jobs().start('poll'))
        except Exception as e: return fail(e)
