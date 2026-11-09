from __future__ import annotations

import os, re
from collections import Counter
from functools import partial
from fastcore.all import L, Path, noop

from ... import errstr
from .jobs import JobError, run_script

__all__ = ['DOC_EXTS', 'STOPPABLE', 'stoppable', 'clip_docs', 'clip_codebase', 'clip_api_spec', 'clip_tree', 'acquire_one',
           'connect_graph', 'register_all']

DOC_EXTS = frozenset({'.md', '.markdown', '.txt', '.rst', '.pdf', '.ipynb', '.html', '.htm'})

BATCH = 8

#: Acquisitions vishalakshi can stop: before the read, fetch or clone, and between the pages, sources or files it files.
STOPPABLE = ('clip', 'grab', 'web', 'crawl', 'github', 'arxiv', 'youtube', 'pdf')
#: The most unread entries a job's result keeps; `n_unread` has the count.
MAX_UNREAD = 500

def stoppable(action):
    "Whether an acquisition by `action` asks a `stop` it is given; a note or a harvest is one call that does not."
    return action in STOPPABLE

def _filed(batch, rows):
    "`(file, row)` pairs for the files `memory.clip` filed, and the files of `batch` it did not reach."
    if rows is None: rows = [{}] * len(batch)   # a memory that reports nothing filed everything it was given
    rows = list(rows)
    return list(zip(batch, rows)), list(batch[len(rows):])

def _batches(xs):
    "`(start, batch)` over `xs` in batches of `BATCH`; vishalakshi asks the stop before each file, so a cancel lands inside one."
    for i in range(0, len(xs), BATCH): yield i, xs[i:i + BATCH]

def _files(target, exts=DOC_EXTS):
    "Documents under `target`, past what litesearch's `dir2files` skips except `docs/` and `examples/`, and past `venv`, `site-packages` and `LEELA_VAULT_SKIP`'s folders."
    from litesearch import dir2files
    from litesearch.data import skip_folder_re
    p = Path(target).expanduser()
    if p.is_file(): return [p]
    if not p.is_dir(): raise JobError(f'nothing to clip at {target}')
    more = ['venv', 'site-packages', *[re.escape(x.strip()) for x in os.getenv('LEELA_VAULT_SKIP', '').split(',') if x.strip()]]
    # without `docs?` in the list, a plain `venv/` would give up every package's docs
    rx = skip_folder_re.replace('examples?|docs?|', '') + f"|(?i:^(?:{'|'.join(more)})$)"
    fs = dir2files(p, skip_folder_re=rx, symlinks=False)
    return sorted(fs.filter(lambda f: f.suffix.lower() in exts and f.is_file()))

def clip_docs(memory, job, report, stop=noop):
    shelf, files = job.params.get('shelf'), _files(job.target)
    if not files: raise JobError(f'no clippable document under {job.target}')
    names = set(map(str, files))
    # a clip resumed from before the walk skipped a folder still lists its files as done
    done = [d for d in job.params.get('_resume', {}).get('done', []) if d in names] if job.resumable else []
    already = set(done)
    pending = [f for f in files if str(f) not in already]
    out = dict(files=list(done), skipped=[], shelf=shelf, n=len(files))
    meta = dict(clipped_from=job.params.get('from') or 'file', clip_job=job.id)
    clipped = []
    for i, batch in _batches(pending):
        if stop(): return out | dict(cancelled=True, unread=list(map(str, pending[i:])), pii=_pii_summary(memory, clipped, shelf))
        rows = memory.clip(batch, shelf=shelf, meta=meta, stop=stop)
        filed, left = _filed(batch, rows)
        for f, r in filed:
            out['skipped' if r.get('skipped') else 'files'].append(str(f))
            if r.get('doc_id'): clipped.append(r['doc_id'])
        if left and getattr(rows, 'cancelled', False):
            # stopped inside the batch: the files before the stop are done, so a resume leaves them
            report(result=out, params=dict(job.params, _resume=dict(done=out['files'] + out['skipped'])))
            return out | dict(cancelled=True, unread=list(map(str, left + pending[i + len(batch):])), pii=_pii_summary(memory, clipped, shelf))
        # a batch whose clip failed is neither done nor skipped, so a retry clips it again
        if left: out.setdefault('failed', []).extend(map(str, left))
        seen = out['files'] + out['skipped']
        report(progress=0.05 + 0.9 * len(seen) / len(files), current=f'{len(seen)} of {len(files)}' + (' · cancelling' if stop() else ''),
            result=out, params=dict(job.params, _resume=dict(done=seen)))
    out['pii'] = _pii_summary(memory, clipped, shelf)
    return out

def _pii_summary(memory, doc_ids, shelf):
    kinds, flagged = Counter(), []
    for did in L(doc_ids).filter():
        r = memory.pii(did, shelf=shelf)
        if not r.get('has_pii'): continue
        flagged.append(memory.ref(did, shelf))
        kinds.update(r.get('kinds') or {})
    return dict(documents=flagged, kinds=dict(kinds), covers='titled names and pattern kinds')

def clip_codebase(memory, search, job, report):
    root = Path(job.target)
    if not root.is_dir(): raise JobError(f'{job.target} is not a folder')
    report(current=f'indexing {root.name}', progress=0.1)
    try: index = dict(synced=search.sync(notebooks=True, graph=True)) if hasattr(search, 'sync') else dict(note='kosha unavailable')
    except Exception as e: index = dict(note=f'index failed ({errstr(e)})')
    report(current='writing the pointer', progress=0.7)
    langs = dict(Counter(f.suffix.lower() for f in root.rglob('*') if f.is_file() and f.suffix))
    top = ', '.join(f'{k} {v}' for k, v in sorted(langs.items(), key=lambda kv: -kv[1])[:6])
    text = (f'# {root.name}\n\nCodebase indexed for search rather than stored as prose. Retrieval '
        f'federates code sections from the index; this document is the pointer to it.\n\n'
        f'- root: `{root}`\n- files by type: {top or "none"}\n'
        f'- backend: {getattr(search, "backend", "") or "unknown"}\n'
        f'- note: {getattr(search, "note", "") or index.get("note", "indexed")}\n')
    meta = dict(kind='codebase', root=str(root), clip_job=job.id, clipped_from='codebase')
    doc = memory.note_pointer(f'Codebase: {root.name}', text, shelf=job.params.get('shelf'), meta=meta)
    return dict(root=str(root), pointer=doc, index=index, types=langs,
        note='source is not duplicated into the shelf; the index is federated at query time')

def clip_api_spec(memory, job, report):
    from .spec import load_spec, op_row, spec_ops
    report(current='reading the specification', progress=0.1)
    spec, src = load_spec(job.target), str(job.target)
    ops = [dict(op_row(o)) for o in spec_ops(spec)]
    info = spec.get('info') or {}
    title = job.params.get('name') or info.get('title') or spec.get('title') or src
    report(current=f'{len(ops)} operations', progress=0.6)
    lines = [f'# {title}\n', f'API specification clipped from `{src}`.',
        f"version {info.get('version') or spec.get('version') or 'unstated'} · {len(ops)} operations\n"]
    for o in ops:
        lines += [f"## {o['verb']} {o['path']}", '', f"`{o['signature']}`" if o.get('signature') else '',
            o.get('summary') or '', f"group: {o['group']}" if o.get('group') else '',
            f"required: {', '.join(o['required'])}" if o.get('required') else '',
            f"docs: {o['docs_url']}" if o.get('docs_url') else '', '']
    meta = dict(kind='api_spec', source=src, clip_job=job.id, operations=len(ops), clipped_from='api_spec')
    doc = memory.note_pointer(f'API: {title}', '\n'.join(lines), shelf=job.params.get('shelf'), meta=meta)
    return dict(source=src, title=title, operations=len(ops), pointer=doc,
        groups=sorted({o['group'] for o in ops if o.get('group')}))

def clip_tree(memory, job, report, stop=noop):
    from .acquire import plan_tree
    plan = plan_tree(job.target)
    if not plan.files: raise JobError(f'no clippable document under {job.target}')
    names = {str(x.path) for x in plan.files}
    # a clip resumed from before the walk skipped a folder still lists its files as done
    done = {d for d in job.params.get('_resume', {}).get('done', []) if d in names} if job.resumable else set()
    out = dict(root=str(plan.root), files=[], n=len(plan.files), shelves=plan.shelves, categories=plan.categories)
    groups = {}
    for x in plan.files:
        if str(x.path) not in done: groups.setdefault((x.shelf, x.category), []).append(x.path)
    seen = len(done)
    for (shelf, category), paths in groups.items():
        meta = dict(category=category, clipped_from='folder', import_root=str(plan.root), clip_job=job.id)
        for _, batch in _batches(paths):
            if stop(): return out | dict(cancelled=True, unread=[str(x.path) for x in plan.files if str(x.path) not in done])
            rows = memory.clip(batch, shelf=shelf, meta=meta, stop=stop)
            filed, left = _filed(batch, rows)
            for p, r in filed:
                out['files'].append(dict(path=str(p), shelf=shelf, category=category,
                    doc_id=r.get('doc_id') or r.get('id'), status='skipped' if r.get('skipped') else 'clipped'))
                done.add(str(p))
            if left and getattr(rows, 'cancelled', False):
                report(result=out, params=dict(job.params, _resume=dict(done=sorted(done))))
                return out | dict(cancelled=True, unread=[str(x.path) for x in plan.files if str(x.path) not in done])
            for p in left: out['files'].append(dict(path=str(p), shelf=shelf, category=category, doc_id=None, status='failed'))
            seen += len(batch)
            report(progress=0.05 + 0.9 * seen / len(plan.files), current=f'{shelf} · {seen} of {len(plan.files)}' + (' · cancelling' if stop() else ''),
                result=out, params=dict(job.params, _resume=dict(done=sorted(done))))
    return out

def _progress(report, every=0.5):
    "vishalakshi's `progress(done, total, step)` as job progress: never backwards, at most one write per `every` seconds."
    import time
    st = dict(at=0.05, t=0.0)
    def f(done, total, step):
        frac = 0.05 + 0.9 * min(1.0, done / max(1, total))
        if frac <= st['at'] or time.time() - st['t'] < every: return
        st.update(at=frac, t=time.time())
        report(progress=frac, current=f'{done} of {total}')
    return f

def acquire_one(memory, job, report, stop=noop):
    "One acquisition; one vishalakshi can stop is given `stop` and reports its progress, and a stopped one ends with `cancelled` and `unread`."
    from .acquire import detect
    action = job.params.get('action') or detect(job.target)
    if action == 'clip': return clip_docs(memory, job, report, stop)
    report(current=f'{action} {job.target}', progress=0.2)
    kw = {k: v for k, v in job.params.items() if k not in ('action', 'shelf', '_resume', 'from', '_cancel')}
    if job.cancellable and stoppable(action): kw |= dict(stop=stop, progress=_progress(report))
    out = dict(memory.acquire(action, job.target, shelf=job.params.get('shelf'), **kw), action=action)
    unread = [str(u) for u in L(out.pop('unread', None) or [])]
    if unread and (out.get('cancelled') or stop()): out |= dict(cancelled=True, unread=unread[:MAX_UNREAD], n_unread=len(unread))
    else: out.pop('cancelled', None)
    return out

def connect_graph(memory, job, report):
    out, names = {}, memory._populated()
    for i, name in enumerate(names):
        report(progress=0.05 + 0.9 * i / max(1, len(names)), current=name)
        try: out[name] = dict(memory._store(name).connect())
        except Exception as e: out[name] = dict(error=errstr(e))
    return dict(shelves=out, topics=len(memory.clusters().get('clusters') or []))

def register_all(jobs, memory, search=None, cwd=None, feeds=None):
    jobs.register('clip', lambda job, report: clip_docs(memory, job, report, partial(jobs.stopping, job.id)))
    jobs.register('clip_tree', lambda job, report: clip_tree(memory, job, report, partial(jobs.stopping, job.id)))
    jobs.register('acquire', lambda job, report: acquire_one(memory, job, report, partial(jobs.stopping, job.id)))
    jobs.register('connect', lambda job, report: connect_graph(memory, job, report))
    jobs.register('clip_codebase', lambda job, report: clip_codebase(memory, search, job, report))
    jobs.register('clip_api_spec', lambda job, report: clip_api_spec(memory, job, report))
    if feeds is not None:
        from .news import poll_feeds
        jobs.register('feeds', lambda job, report: poll_feeds(memory, feeds,
            force=bool(job.params.get('force')), only=job.params.get('only') or '', report=report))
    jobs.register('tidy', lambda job, report: dict(candidates=memory.noisy_candidates(
        shelf=job.params.get('shelf'), k=int(job.params.get('k') or 20))))
    jobs.register('poll', lambda job, report: jobs.poll_due())
    jobs.register('script', lambda job, report: run_script(job.target, cwd=cwd))
    jobs.register('migrate_memory', lambda job, report: _migrate(job, report))
    jobs.register('tool_env', _tool_env)
    return jobs

def _tool_env(job, report):
    from ..learn.toolenv import tool_job
    return tool_job(job, report)

def _migrate(job, report):
    from ...migrate_memory import migrate
    report(current='reading the old store', progress=0.2)
    return migrate(shelf=job.params.get('shelf') or 'leela', vault_path=job.params.get('vault'),
        old=job.params.get('old'), apply=bool(job.params.get('apply')))
