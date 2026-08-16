from __future__ import annotations

import os, re
from collections import Counter
from fastcore.all import AttrDict, L, Path

from .clip import DOC_EXTS

__all__ = ['ACTIONS', 'SKIP', 'detect', 'plan_tree', 'category_for']

ACTIONS = (('grab', 'a page, a paper, a pdf — read it and file it'),
           ('web', 'search the web and file what comes back'),
           ('crawl', 'follow a site and file every page'),
           ('github', 'a repository, as prose'),
           ('arxiv', 'a paper by id or url'),
           ('youtube', 'a video, by its transcript'),
           ('harvest', 'a json api, page by page'),
           ('note', 'write it down yourself'))

SKIP = {'build', 'dist', 'node_modules', '__pycache__', '.venv', 'venv', 'site-packages', 'target',
        'tmp', 'temp', 'out', 'output', 'outputs', '.git', '.mypy_cache', '.pytest_cache', '.tox',
        *[x.strip().lower() for x in os.getenv('LEELA_VAULT_SKIP', '').split(',') if x.strip()]}

CATS = {'spec': ('spec', 'requirement', 'rfc', 'openapi', 'schema', 'contract'),
        'design': ('design', 'architecture', 'adr', 'rfd', 'proposal'),
        'notes': ('note', 'journal', 'diary', 'log', 'minutes', 'meeting'),
        'docs': ('doc', 'guide', 'manual', 'handbook', 'readme', 'tutorial'),
        'research': ('paper', 'research', 'arxiv', 'study', 'literature'),
        'reference': ('reference', 'api', 'glossary', 'faq'),
        'report': ('report', 'analysis', 'findings', 'review', 'postmortem')}

ARXIV = re.compile(r'^\d{4}\.\d{4,5}(v\d+)?$')

def detect(target):
    s = str(target or '').strip()
    if not s: return 'note'
    if ARXIV.match(s) or 'arxiv.org' in s: return 'arxiv'
    if re.search(r'(youtube\.com|youtu\.be)', s): return 'youtube'
    if re.search(r'github\.com/[^/]+/[^/]+', s): return 'github'
    if s.startswith(('http://', 'https://')): return 'grab'
    return 'clip' if Path(s).expanduser().exists() else 'note'

def _slug(s): return re.sub(r'[^a-z0-9]+', '_', str(s).lower()).strip('_')[:48] or 'documents'

def category_for(path):
    s = ' '.join(Path(path).parts[-4:]).lower().replace('_', ' ').replace('-', ' ')
    k, n = max(((k, sum(c in s for c in cues)) for k, cues in CATS.items()), key=lambda kv: kv[1])
    return k if n else 'other'

def _generated(rel): return any(p.lower() in SKIP or p.startswith('.') for p in rel.parts[:-1])

def plan_tree(root, exts=DOC_EXTS):
    root = Path(root).expanduser().resolve()
    if not root.is_dir(): raise ValueError(f'{root} is not a folder')
    found = L(p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in exts)
    kept = found.filter(lambda p: not _generated(p.relative_to(root)))
    skipped = found.filter(lambda p: _generated(p.relative_to(root)))
    tops = Counter(p.relative_to(root).parts[0] for p in kept if len(p.relative_to(root).parts) > 1)
    split = len(tops) > 1
    rows = L()
    for p in kept:
        rel = p.relative_to(root)
        shelf = _slug(rel.parts[0] if split and len(rel.parts) > 1 else root.name)
        rows.append(AttrDict(path=p, relative=str(rel), shelf=shelf, category=category_for(rel)))
    return AttrDict(root=root, files=rows, skipped=skipped,
                    shelves=dict(Counter(x.shelf for x in rows)),
                    categories=dict(Counter(x.category for x in rows)))
