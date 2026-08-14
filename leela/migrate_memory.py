"Move leela's old litesearch memory into a vishalakshi vault shelf."

from __future__ import annotations

import argparse, sqlite3, tempfile
from pathlib import Path

from . import leela_cfg
from .blocks.memory.memory import _registered_encoder, memory_path

__all__ = ['old_memory_path', 'read_old', 'migrate']

STORE = 'memory'

def old_memory_path(path=None):
    "Where leela's pre-vault memory lives."
    return Path(path) if path else leela_cfg/'memory'/'web.db'

def read_old(path):
    "Every document in the old store, as dicts with title/source/kind/meta/text."
    from vishalakshi import Vault
    src = Path(path)
    if not src.is_file(): return []
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)/'old.db'
        with sqlite3.connect(f'file:{src}?mode=ro', uri=True) as s, sqlite3.connect(work) as d:
            s.backup(d)
        v = Vault(work, store=STORE, offline=True)
        docs = [v.document(d['id']) for d in v.sources()]
        return [dict(title=doc.title, source=doc.source, kind=doc.kind,
                     meta=dict(doc.meta or {}), text=doc.text)
                for doc in docs if (doc.text or '').strip()]

def migrate(shelf='leela', vault_path=None, old=None, apply=False, encoder=None, offline=False):
    "Re-add every old document into `shelf`. Idempotent by `source`."
    docs = read_old(old_memory_path(old))
    report = dict(found=len(docs), moved=[], skipped=[], shelf=shelf, applied=apply)
    if not docs: return report
    from vishalakshi import Vault
    store = 'store' if shelf in (None, '', 'main') else shelf
    target_path = memory_path(vault_path)
    target = Vault(target_path, store=store, offline=offline,
                   encoder=None if offline else (_registered_encoder(target_path, store) or encoder))
    report['vault'], report['store'] = str(target.path), target.name
    have = {str(d['source']) for d in target.sources()}
    for d in docs:
        if d['source'] in have:
            report['skipped'].append((d['title'], 'already in the shelf'))
            continue
        if apply:
            target.add(d['text'], d['title'], source=d['source'], kind=d['kind'], meta=d['meta'])
        report['moved'].append((d['title'], d['kind']))
    return report

def _main(argv=None):
    p = argparse.ArgumentParser(prog='python -m leela.migrate_memory',
                                description=__doc__.splitlines()[0])
    p.add_argument('--shelf', default='leela',
                   help="vault shelf to write into ('main' for the vault's main store)")
    p.add_argument('--vault', default=None, help='vault file; default $VISHALAKSHI_VAULT or ~/.vishalakshi/vault.db')
    p.add_argument('--old', default=None, help=f'the old memory db (default: {old_memory_path()})')
    p.add_argument('--apply', action='store_true', help='actually write; without it, only report')
    a = p.parse_args(argv)
    src = old_memory_path(a.old)
    if not src.is_file():
        print(f'nothing to migrate: {src} does not exist')
        return 0
    r = migrate(shelf=a.shelf, vault_path=a.vault, old=a.old, apply=a.apply)
    print(f"{r['found']} document(s) in {src}")
    if r.get('vault'): print(f"target: {r['vault']} · store {r['store']}")
    for title, kind in r['moved']:
        print(f"  {'moved ' if a.apply else 'would move'}  {kind:12} {title}")
    for title, why in r['skipped']:
        print(f"  skipped                  {title}  ({why})")
    if not a.apply and r['moved']:
        print('\nnothing was written. re-run with --apply to move them.')
    return 0

if __name__ == '__main__':
    raise SystemExit(_main())
