"What clipping a thing into the vault means, which depends on what the thing is."

from __future__ import annotations

from collections import Counter
from fastcore.all import L, Path

from ... import errstr
from .jobs import JobError, run_script

__all__ = ['DOC_EXTS', 'clip_docs', 'clip_codebase', 'clip_api_spec', 'register_all']

DOC_EXTS = frozenset({'.md', '.markdown', '.txt', '.rst', '.pdf', '.ipynb', '.html', '.htm'})

BATCH = 8

def _files(target, exts=DOC_EXTS):
    p = Path(target)
    if p.is_file(): return [p]
    if not p.is_dir(): raise JobError(f'nothing to clip at {target}')
    return sorted(f for f in p.rglob('*') if f.is_file() and f.suffix.lower() in exts)

def clip_docs(memory, job, report):
    "Prose into the workspace shelf, committed in batches so partial work is usable."
    shelf, files = job.params.get('shelf'), _files(job.target)
    if not files: raise JobError(f'no clippable document under {job.target}')
    done = job.params.get('_resume', {}).get('done', []) if job.resumable else []
    already = set(done)
    pending = [f for f in files if str(f) not in already]
    out = dict(files=list(done), skipped=[], shelf=shelf, n=len(files))
    meta = dict(clipped_from=job.params.get('from') or 'file', clip_job=job.id)
    clipped = []
    for i in range(0, len(pending), BATCH):
        batch = pending[i:i + BATCH]
        rows = memory.clip(batch, shelf=shelf, meta=meta)
        for f, r in zip(batch, rows or [{}] * len(batch)):
            out['skipped' if r.get('skipped') else 'files'].append(str(f))
            if r.get('doc_id'): clipped.append(r['doc_id'])
        seen = out['files'] + out['skipped']
        report(progress=0.05 + 0.9 * len(seen) / len(files), current=f'{len(seen)} of {len(files)}',
            result=out, params=dict(job.params, _resume=dict(done=seen)))
    out['pii'] = _pii_summary(memory, clipped, shelf)
    return out

def _pii_summary(memory, doc_ids, shelf):
    "Which of the documents just clipped carry personal information, per the vault's own report."
    kinds, flagged = Counter(), []
    for did in L(doc_ids).filter():
        r = memory.pii(did, shelf=shelf)
        if not r.get('has_pii'): continue
        flagged.append(memory.ref(did, shelf))
        kinds.update(r.get('kinds') or {})
    return dict(documents=flagged, kinds=dict(kinds), covers='titled names and pattern kinds')

def clip_codebase(memory, search, job, report):
    "Index the repository with kosha, then file one pointer document naming that index."
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
    "One document per spec, one section per operation, so an endpoint stays addressable."
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

def register_all(jobs, memory, search=None, cwd=None):
    "Wire every clip kind, plus the two general ones, onto a `Jobs`."
    jobs.register('clip', lambda job, report: clip_docs(memory, job, report))
    jobs.register('clip_codebase', lambda job, report: clip_codebase(memory, search, job, report))
    jobs.register('clip_api_spec', lambda job, report: clip_api_spec(memory, job, report))
    jobs.register('tidy', lambda job, report: dict(candidates=memory.noisy_candidates(
        shelf=job.params.get('shelf'), k=int(job.params.get('k') or 20))))
    jobs.register('poll', lambda job, report: jobs.poll_due())
    jobs.register('script', lambda job, report: run_script(job.target, cwd=cwd))
    jobs.register('migrate_memory', lambda job, report: _migrate(job, report))
    return jobs

def _migrate(job, report):
    "The memory migration as a job, so it has progress and a retry instead of a terminal."
    from ...migrate_memory import migrate
    report(current='reading the old store', progress=0.2)
    return migrate(shelf=job.params.get('shelf') or 'leela', vault_path=job.params.get('vault'),
        old=job.params.get('old'), apply=bool(job.params.get('apply')))
