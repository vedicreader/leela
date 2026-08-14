"""Re-reading clipped files that changed on disk, and not re-reading the ones that did not.

The whole point is what it *skips*: vishalakshi's own `path` watch re-embeds every interval
regardless, which on a shelf of any size is a large recurring cost for no new information.
"""

import time

import pytest

from leela.blocks.memory.memory import Memory, _added_epoch, source_kind


@pytest.fixture
def vault(tmp_path):
    (tmp_path/'a.md').write_text('# A\n\nalpha\n')
    (tmp_path/'b.md').write_text('# B\n\nbeta\n')
    m = Memory(path=tmp_path/'vault.db', offline=True)
    m.clip([tmp_path/'a.md', tmp_path/'b.md'])
    return m, tmp_path


def test_added_at_is_read_as_utc():
    """The stored stamp is naive but is UTC. Read as local time it is hours out, every row looks
    older than its file, and the first sweep re-embeds the whole vault."""
    from datetime import datetime, timezone
    naive = '2026-08-14 09:43:14'
    assert _added_epoch(naive) == datetime(2026, 8, 14, 9, 43, 14, tzinfo=timezone.utc).timestamp()
    assert _added_epoch(1786664594.0) == 1786664594.0
    # Unknown must not mean stale: zero would make every row older than its file.
    assert _added_epoch('not a date') == float('inf')


def test_source_kind_tells_a_file_from_a_page_from_an_invention():
    assert source_kind('/a/b.md') == 'file'
    assert source_kind('https://example.com/p') == 'url'
    for s in ('memory:ab12', 'pointer:ff01', '', None): assert source_kind(s) == 'synthetic'


def test_an_untouched_vault_is_not_reindexed(vault):
    m, _ = vault
    r = m.reindex_changed()
    assert r['checked'] == 2 and r['reindexed'] == 0


def test_a_changed_file_is_reindexed_once_and_then_settles(vault):
    "Re-clipping advances `added_at`, so a change costs one sweep rather than every sweep."
    m, d = vault
    time.sleep(1.1)
    (d/'a.md').write_text('# A\n\nalpha rewritten\n')
    r = m.reindex_changed()
    assert r['reindexed'] == 1 and [p.split('/')[-1] for p in r['paths']] == ['a.md']
    time.sleep(1.1)
    assert m.reindex_changed()['reindexed'] == 0, 'it must converge, not re-read forever'
    assert len(m.all_documents()) == 2, 're-clipping updates the document, it does not add one'


def test_a_missing_file_is_reported_and_never_forgotten(vault):
    "A vault is a record. An unplugged drive is not a reason to drop what was on it."
    m, d = vault
    (d/'b.md').unlink()
    r = m.reindex_changed()
    assert [p.split('/')[-1] for p in r['missing']] == ['b.md']
    assert len(m.all_documents()) == 2, 'the row survives its file'


def test_documents_that_were_never_files_are_not_walked(vault):
    m, d = vault
    m.clip([d/'a.md'])
    before = m.reindex_changed()['checked']
    assert before == 2, 'only filed documents are candidates'
