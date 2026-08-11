"""Moving leela's pre-vault memory into a vishalakshi vault shelf.

The interesting cases are not "does it copy text". They are the two ways a migration silently
corrupts things: reading a stale snapshot, and running twice.
"""

import sqlite3

import pytest

from leela.migrate_memory import migrate, read_old

pytest.importorskip('vishalakshi')


def _old_store(path, docs):
    "An old-format leela memory: a litesearch store named `memory`, which is what Memory wrote."
    from vishalakshi import Vault
    v = Vault(path, store='memory', offline=True)
    for title, kind, text in docs:
        v.add(text, title, source=f'{kind}://{title.replace(" ", "-")}', kind=kind, meta={'agent': {'revision': 1}})
    return v


def test_documents_come_across_with_their_kind_and_meta(tmp_path):
    _old_store(tmp_path/'web.db', [('Working state', 'agent-state', '# Rules\n\nBe careful.'),
                                   ('core', 'agent-note', 'Text between tool calls is not shown.')])
    got = {d['title']: d for d in read_old(tmp_path/'web.db')}
    assert set(got) == {'Working state', 'core'}
    assert got['Working state']['kind'] == 'agent-state'      # the kind is the seam the panel filters on
    assert got['core']['meta']['agent']['revision'] == 1      # agent revision chains must survive
    assert 'Be careful' in got['Working state']['text']


def test_a_deleted_document_stays_deleted(tmp_path):
    """A forgotten document must not come back.

    litesearch runs SQLite in WAL mode, so a deletion lives in `web.db-wal` until something
    checkpoints it. Copying the single `.db` file hands back the state *before* the delete. This
    happened: a migration built on `shutil.copy` resurrected fifteen documents that had been
    purged minutes earlier, and would have re-filed them as new.
    """
    v = _old_store(tmp_path/'web.db', [('keep', 'agent-note', 'keep this one'),
                                       ('drop', 'agent-note', 'this one was forgotten')])
    doc_id = next(d['id'] for d in v.sources() if d['title'] == 'drop')
    v.forget(doc_id)
    assert (tmp_path/'web.db-wal').exists(), 'precondition: the delete is still in the WAL'

    titles = [d['title'] for d in read_old(tmp_path/'web.db')]
    assert titles == ['keep'], f'a deleted document came back: {titles}'


def test_the_source_file_is_never_written_to(tmp_path):
    "Opening a vault registers its encoder, so the migration must read a copy, not the original."
    _old_store(tmp_path/'web.db', [('a', 'agent-note', 'text')])
    before = sqlite3.connect(f"file:{tmp_path/'web.db'}?mode=ro", uri=True)
    tables = {r[0] for r in before.execute("select name from sqlite_master where type='table'")}
    before.close()

    read_old(tmp_path/'web.db')

    after = sqlite3.connect(f"file:{tmp_path/'web.db'}?mode=ro", uri=True)
    now = {r[0] for r in after.execute("select name from sqlite_master where type='table'")}
    after.close()
    assert now == tables, f'reading the old store added {now - tables}'


def test_running_twice_moves_nothing_the_second_time(tmp_path):
    "Idempotent by `source`, because leela's memory panel has already been on the wrong end of this."
    _old_store(tmp_path/'web.db', [('one', 'agent-note', 'first'), ('two', 'agent-state', 'second')])
    kw = dict(vault_path=tmp_path/'vault.db', old=tmp_path/'web.db', shelf='leela', offline=True)

    first = migrate(apply=True, **kw)
    assert len(first['moved']) == 2 and not first['skipped']

    again = migrate(apply=True, **kw)
    assert not again['moved'], 'a second run re-filed documents'
    assert len(again['skipped']) == 2


def test_nothing_is_written_without_apply(tmp_path):
    _old_store(tmp_path/'web.db', [('one', 'agent-note', 'first')])
    kw = dict(vault_path=tmp_path/'vault.db', old=tmp_path/'web.db', shelf='leela', offline=True)

    dry = migrate(apply=False, **kw)
    assert len(dry['moved']) == 1 and dry['applied'] is False

    from vishalakshi import Vault
    assert not Vault(tmp_path/'vault.db', store='leela', offline=True).sources()
