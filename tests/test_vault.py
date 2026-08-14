"""The vault surface behind clip: shelf naming, what a clip becomes, and cadence.

Offline throughout, so nothing loads an encoder or opens a socket.
"""

import pytest

from leela.blocks.memory.memory import GLOBAL, Memory, memory_shelf, safe_shelf


@pytest.fixture
def mem(tmp_path, monkeypatch):
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    return Memory(shelf='my-repo', path=tmp_path/'vault.db', offline=True)


def _ids(m): return [d.get('doc_id') or d.get('id') for d in m.documents()]


def test_a_folder_name_becomes_a_shelf_a_hyphen_cannot_break(tmp_path):
    """A shelf is a table-name prefix, so the name reaches raw SQL.

    litesearch's entity resolution has one unquoted statement a hyphen breaks, and folder names
    carry hyphens and dots routinely.
    """
    assert safe_shelf('my-repo') == safe_shelf('My.Repo') == 'my_repo'
    assert safe_shelf('') == safe_shelf(None) == safe_shelf('--') == 'main'
    assert memory_shelf('/tmp/some-project') == 'some_project'
    assert memory_shelf(None) == 'main', 'no folder open is the main shelf, not a crash'
    assert memory_shelf(f'/tmp/{GLOBAL}') == 'main', 'the global shelf is reserved'


def test_a_clip_lands_is_judged_and_the_judgement_outlives_it(mem, tmp_path):
    """One walk through the whole surface: ingest, retrieve, report, judge, re-ingest.

    The PII assertions are the load-bearing ones. Coverage is *titled* names plus pattern kinds,
    so `Ada Lovelace` is deliberately not found — a surface that said "no personal information"
    rather than "none found" would be lying, and `scanned_ner` is how it tells the two apart.
    """
    (tmp_path/'notes.md').write_text('# Retrieval\n\nDurable notes about recall and ranking.\n')
    (tmp_path/'minute.md').write_text(
        '# Minute\n\nSigned by Dr Charles Babbage. Deliver to 42 Elm Street, London.\n')
    (tmp_path/'plain.md').write_text('# Plain\n\nAda Lovelace wrote about ranking.\n')
    assert len(mem.clip(list(tmp_path.glob('*.md')))) == 3

    shelves = mem.shelves()
    assert [s['store'] for s in shelves] == ['my_repo'], 'the sanitised name, not the folder name'
    assert shelves[0]['docs'] == 3
    hits = mem.search('recall and ranking')
    assert hits and mem.read(hits[0]['node_id']).get('text')

    by_title = {d['title']: (d.get('doc_id') or d.get('id')) for d in mem.documents()}
    minute = mem.pii(by_title['minute'])
    assert minute['has_pii'] and set(minute['kinds']) == {'person', 'address'}
    plain = mem.pii(by_title['plain'])
    assert not plain['has_pii'], 'a bare name is not found, which is why the badge says "found"'
    assert plain['scanned_ner'], 'and it must still say that it looked'

    # A ref carries its shelf: a doc id is content-addressed *per shelf*, so it is not unique alone.
    assert mem.ref(by_title['notes']).startswith('my_repo|')

    # `doc_marks` is keyed (doc_id, store) outside the shelf prefix, so re-adding cannot erase it.
    did = by_title['minute']
    assert mem.mark_noisy(did, reason='changelog')['noisy'] == 1
    mem.clip([tmp_path/'minute.md'], force=True)
    assert mem._open().marks(did).get('noisy'), 'the judgement outlived the document'
    assert mem.mark_noisy(did, noisy=False)['noisy'] == 0
    assert isinstance(mem.noisy_candidates(), list), 'no opinion on a tiny corpus, but no crash'


def test_a_cadence_is_a_watch_and_a_url_watch_forces_a_refetch(mem):
    """`remind` keeps this offline; the `force` assertion is read off the stored params.

    Without `force` a page whose content changed reports "already ingested" for ever, because a
    doc id is content-addressed on `source|title` and the source did not change.
    """
    w = mem.watch('review the minute', action='remind', every='1d')
    assert w['every'] == 86400.0 and 'force' not in (w['params'] or {})
    assert len(mem.watches()) == 1

    got = mem.poll()
    assert got['checked'] == 1 and got['ran'] == 1
    mem.unwatch(w['id'])
    assert mem.watches() == []

    for action in ('url', 'arxiv', 'youtube'):
        w = mem.watch(f'https://example.com/{action}', action=action, every='6h')
        assert w['params'].get('force') is True, f'{action} must refetch'
        mem.unwatch(w['id'])


def test_a_clips_pii_report_covers_what_that_clip_wrote(mem, tmp_path):
    """The summary is about the documents this job clipped, not about the shelf.

    It used to re-list `documents(limit=400)`, so clipping one clean file into a shelf that
    already held a CV reported personal information the clip had nothing to do with.
    """
    from leela.blocks.jobs.clip import _pii_summary
    (tmp_path/'cv.md').write_text('# CV\n\nDr Charles Babbage, ada@example.com, 555-123-4567.\n')
    (tmp_path/'clean.md').write_text('# Notes\n\nRanking and recall, no one in particular.\n')
    rows = {r['title']: r['doc_id'] for r in mem.clip(sorted(tmp_path.glob('*.md')))}

    clean = _pii_summary(mem, [rows['clean']], mem.shelf_name)
    assert clean['documents'] == [] and clean['kinds'] == {}, 'the CV is in the shelf, not in this clip'
    cv = _pii_summary(mem, [rows['cv']], mem.shelf_name)
    assert cv['documents'] == [mem.ref(rows['cv'], mem.shelf_name)]
    assert set(cv['kinds']) >= {'email', 'phone'}


def test_purge_attempts_each_document_once(mem, tmp_path):
    "The three listings overlap; a document whose forget fails must not be retried per duplicate."
    (tmp_path/'a.md').write_text('# A\n\nDurable prose about ranking.\n')
    mem.clip([tmp_path/'a.md'])
    doc_id = (mem.documents() or [{}])[0]['id']
    tried = []
    mem.forget = lambda i: (tried.append(i), False)[1]      # a forget that never succeeds
    assert mem.purge() == 0
    assert tried.count(doc_id) == 1, 'one attempt per document, however many listings name it'
