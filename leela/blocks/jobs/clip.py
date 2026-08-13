"""What clipping a thing into the vault means, which depends on what the thing is.

Three kinds, three pipelines, because they are not the same shape:

- **a document** is prose: a tab, a file, a PDF, a notebook, a page already read. It goes in as
  chunks, which is vishalakshi's ordinary path.
- **a codebase** is not prose. Kosha owns code, and the vault already knows it -- `Vault.context`
  federates code sections in -- so what lands in the shelf is one pointer document naming the
  index, not a copy of the source. A clipped repository then tracks its index instead of ageing
  into a snapshot of it.
- **an API spec** is structured. `ramabana.spec` parses it into operations already signed by
  `fastcore.apisurface`, so each operation becomes a section and stays individually retrievable.

Every handler takes `(job, report)` and returns a JSON-safe dict.
"""

from __future__ import annotations

import json
from fastcore.all import Path, first

from ... import errstr
from .jobs import JobError, run_script

__all__ = ['DOC_EXTS', 'clip_docs', 'clip_codebase', 'clip_api_spec', 'register_all']

#: Narrower than litesearch's list on purpose: a clip is a deliberate act, so the surface offers
#: what a person would call a document.
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
    pending = [f for f in files if str(f) not in set(done)]
    out = dict(files=list(done), skipped=[], shelf=shelf, n=len(files))
    meta = dict(clipped_from=job.params.get('from') or 'file', clip_job=job.id)
    for i in range(0, len(pending), BATCH):
        batch = pending[i:i + BATCH]
        rows = memory.clip(batch, shelf=shelf, meta=meta)
        for f, r in zip(batch, rows or [{}] * len(batch)): out['skipped' if r.get('skipped') else 'files'].append(str(f))
        seen = out['files'] + out['skipped']
        report(progress=0.05 + 0.9 * len(seen) / len(files), current=f'{len(seen)} of {len(files)}',
            result=out, params=dict(job.params, _resume=dict(done=seen)))
    out['pii'] = _pii_summary(memory, out['files'], shelf)
    return out


def _pii_summary(memory, paths, shelf):
    """Which clipped documents carry personal information, per the vault's own report.

    Titled names and pattern kinds only. A bare name is not found, and an unstructured address is
    not masked, so a surface showing this says "found", never "none".
    """
    kinds, flagged = {}, []
    for d in memory.documents(limit=400):
        did = d.get('doc_id') or d.get('id')
        if not did: continue
        r = memory.pii(did, shelf=shelf)
        if not r.get('has_pii'): continue
        flagged.append(memory.ref(did, shelf))
        for k, n in (r.get('kinds') or {}).items(): kinds[k] = kinds.get(k, 0) + n
    return dict(documents=flagged, kinds=kinds, covers='titled names and pattern kinds')


def clip_codebase(memory, search, job, report):
    "Index the repository with kosha, then file one pointer document naming that index."
    root = Path(job.target)
    if not root.is_dir(): raise JobError(f'{job.target} is not a folder')
    report(current=f'indexing {root.name}', progress=0.1)
    try: index = dict(synced=search.sync(notebooks=True, graph=True)) if hasattr(search, 'sync') else dict(note='kosha unavailable')
    except Exception as e: index = dict(note=f'index failed ({errstr(e)})')
    report(current='writing the pointer', progress=0.7)

    langs = {}
    for f in root.rglob('*'):
        if f.is_file() and f.suffix: langs[f.suffix.lower()] = langs.get(f.suffix.lower(), 0) + 1
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
    report(current='reading the specification', progress=0.1)
    spec, src = _load_spec(job.target), str(job.target)
    ops = _spec_ops(spec)
    if not ops: raise JobError(f'{src} declares no operations this can read')
    info = spec.get('info') or {}
    title = job.params.get('name') or info.get('title') or src
    report(current=f'{len(ops)} operations', progress=0.6)

    lines = [f'# {title}\n', f'API specification clipped from `{src}`.',
        f"version {info.get('version') or 'unstated'} · {len(ops)} operations\n"]
    for o in ops:
        lines += [f"## {o['verb']} {o['path']}", '', f"`{o['signature']}`" if o.get('signature') else '',
            o.get('summary') or '', f"group: {o['group']}" if o.get('group') else '',
            f"required: {', '.join(o['required'])}" if o.get('required') else '',
            f"docs: {o['docs_url']}" if o.get('docs_url') else '', '']
    meta = dict(kind='api_spec', source=src, clip_job=job.id, operations=len(ops), clipped_from='api_spec')
    doc = memory.note_pointer(f'API: {title}', '\n'.join(lines), shelf=job.params.get('shelf'), meta=meta)
    return dict(source=src, title=title, operations=len(ops), pointer=doc,
        groups=sorted({o['group'] for o in ops if o.get('group')}))


def _load_spec(src):
    """A spec from a url, a path or a parsed dict.

    ramabana's `load_spec` is JSON only, and most specifications in the world are YAML, so YAML is
    read here rather than left to fail inside `json.loads` with nothing actionable to say.
    """
    if isinstance(src, dict): return src
    s = str(src)
    if s.lower().endswith(('.yaml', '.yml')): return _yaml(_read_spec_text(s), s)
    try:
        from ramabana.spec import load_spec
        return load_spec(s)
    except ImportError: return json.loads(_read_spec_text(s))


def _read_spec_text(s):
    if s.startswith(('http://', 'https://')):
        import httpx2 as httpx
        return httpx.get(s, follow_redirects=True, timeout=30).text
    p = Path(s).expanduser()
    if not p.is_file(): raise JobError(f'no specification at {s}')
    return p.read_text()


def _yaml(text, src):
    # pyyaml, not gheasy: gheasy's yaml is a writer, and depending on it pulls in ghapi and cyclopts.
    try: import yaml
    except ImportError: raise JobError(f'{src} looks like YAML; install pyyaml to clip it')
    d = yaml.safe_load(text)
    if not isinstance(d, dict): raise JobError(f'{src} did not parse as a specification')
    return d


def _spec_ops(spec):
    "Operation rows via ramabana, falling back to reading `paths` when fastspec is absent."
    try:
        from ramabana.spec import op_row, spec_ops
        return [dict(op_row(o)) for o in spec_ops(spec)]
    except Exception: return _paths_ops(spec)


def _paths_ops(spec, mx=400):
    "The minimum an OpenAPI document guarantees, when fastspec cannot be reached."
    verbs = ('get', 'post', 'put', 'patch', 'delete', 'head', 'options')
    out = []
    for path, item in (spec.get('paths') or {}).items():
        if not isinstance(item, dict): continue
        for verb, op in item.items():
            if verb.lower() not in verbs or not isinstance(op, dict): continue
            name = op.get('operationId') or f"{verb}_{str(path).strip('/').replace('/', '_')}"
            req = [p.get('name') for p in (op.get('parameters') or [])
                if isinstance(p, dict) and p.get('required') and p.get('name')]
            out.append(dict(group=first(op.get('tags') or []) or '', name=name, verb=verb.upper(), path=str(path),
                summary=(op.get('summary') or op.get('description') or '').strip()[:400], required=req,
                signature=f"{name}({', '.join(req)})", docs_url=(op.get('externalDocs') or {}).get('url') or ''))
            if len(out) >= mx: return out
    return out


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
