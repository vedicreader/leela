"""Move leela's old litesearch memory into a vishalakshi vault shelf.

    python -m leela.migrate_memory                 # report what would move
    python -m leela.migrate_memory --apply         # move it
    python -m leela.migrate_memory --shelf main    # into the vault's main store instead

Run once, when leela's memory moves from `leela_cfg/memory/web.db` to a vault. Both stores are
litesearch underneath -- `Vault` is a litesearch `Index` with a `kind` on every document -- so the
old file opens as a vault directly, with `store='memory'` naming the tables leela wrote.

The documents are re-added rather than copied. Their vectors were made by Kosha's embedder, which
is code-trained, and the vault embeds prose with a prose encoder; carrying the old vectors across
would leave every one of them unfindable by meaning. Re-adding re-embeds, which is the point.

Reading happens on a *copy*. Opening a vault registers the store's encoder, and that is a write --
so the original file is never opened at all, and stays exactly as leela left it.

The default target is a `leela` shelf rather than the vault's main store. A store records the
encoder that wrote it, and mixing two in one store makes distances across them meaningless -- a
personal vault read with one encoder should not quietly acquire documents embedded with another. A
shelf is a partition, so leela's memory keeps its own store and stops diluting the ranking of a
corpus it has nothing to do with.

`encoder=None` means vishalakshi's default, `potion-multilingual-128M`. Not the English-only
`retrieval` alias, which is faster to load but cannot read Devanagari -- and a vault holding both
source code commentary and Sanskrit wants one encoder across all of it. Code is the deliberate
exception: kosha embeds identifiers with a code-trained model, and leela's search block owns that
index.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import tempfile
from pathlib import Path

from . import leela_cfg

__all__ = ['old_memory_path', 'read_old', 'migrate']

STORE = 'memory'          # the litesearch store name leela's Memory wrote under


def old_memory_path(path=None):
    "Where leela's pre-vault memory lives."
    return Path(path) if path else leela_cfg/'memory'/'web.db'


def vault_path(path=None):
    "The vault file vishalakshi would use, without importing it."
    import os
    return Path(path or os.getenv('VISHALAKSHI_VAULT') or Path.home()/'.vishalakshi'/'vault.db')


def _registered_encoder(path, store):
    "Which encoder wrote `store`, read straight off the registry so no Vault has to be built."
    p = vault_path(path)
    if not p.is_file(): return None
    try:
        with sqlite3.connect(f'file:{p}?mode=ro', uri=True) as c:
            r = c.execute('select encoder from vault_stores where store=?', (store,)).fetchone()
        return r[0] if r else None
    except Exception:
        return None      # no registry yet, or a file that is not a vault: the caller's choice stands


def read_old(path):
    """Every document in the old store, as `(title, source, kind, meta, text)`.

    Copies first: `Vault.__init__` registers the store's encoder, so opening the original would
    write to it. A migration must not modify the thing it is migrating from.
    """
    from vishalakshi import Vault
    src = Path(path)
    if not src.is_file(): return []
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)/'old.db'
        # SQLite's online backup, not shutil.copy: the database is in WAL mode, so recent writes
        # -- including deletions -- live in `web.db-wal` until a checkpoint folds them in. Copying
        # the one file hands back a stale snapshot. This resurrected documents that had already
        # been deleted, which a migration doing it silently would have re-filed as new.
        with sqlite3.connect(f'file:{src}?mode=ro', uri=True) as s, sqlite3.connect(work) as d:
            s.backup(d)
        # `offline=True` keeps this to FTS and hashed n-grams: nothing here is searched, only read,
        # and loading a real encoder to read text would be a model download for no reason.
        v = Vault(work, store=STORE, offline=True)
        out = []
        for d in v.sources():
            doc = v.document(d['id'])
            if (doc.text or '').strip():
                out.append(dict(title=doc.title, source=doc.source, kind=doc.kind,
                                meta=dict(doc.meta or {}), text=doc.text))
        return out


def migrate(shelf='leela', vault_path=None, old=None, apply=False, encoder=None, offline=False):
    """Re-add every old document into `shelf`. Returns what was moved, skipped and why.

    Idempotent: a document whose `source` is already in the shelf is left alone, so running this
    twice is a no-op rather than a duplicate. That matters -- leela's memory panel has already been
    on the receiving end of a job that appended instead of skipping.
    """
    docs = read_old(old_memory_path(old))
    report = dict(found=len(docs), moved=[], skipped=[], shelf=shelf, applied=apply)
    if not docs: return report

    from vishalakshi import Vault
    # Open the target store *directly* rather than `Vault(path).shelf(name)`. Reaching a shelf
    # through the root instantiates the root store too, and a vault whose main store was written
    # by a different encoder warns about mixed distances every time -- for a store this is not
    # even touching. And adopt whatever already wrote the store: a second encoder in one store is
    # what that warning is for, and the caller's preference does not outrank the vectors on disk.
    store = 'store' if shelf in (None, '', 'main') else shelf
    target = Vault(vault_path, store=store, offline=offline,
                   encoder=None if offline else (_registered_encoder(vault_path, store) or encoder))
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
    p = argparse.ArgumentParser(prog='python -m leela.migrate_memory', description=__doc__.splitlines()[0])
    p.add_argument('--shelf', default='leela', help="vault shelf to write into ('main' for the vault's main store)")
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
    for title, kind in r['moved']: print(f"  {'moved ' if a.apply else 'would move'}  {kind:12} {title}")
    for title, why in r['skipped']: print(f"  skipped                  {title}  ({why})")
    if not a.apply and r['moved']:
        print('\nnothing was written. re-run with --apply to move them.')
    return 0


if __name__ == '__main__': sys.exit(_main())
