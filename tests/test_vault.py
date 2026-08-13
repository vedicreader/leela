"""Clipping into the vault: shelves, what a judgement survives, and a cadence.

Feature flows rather than one assertion each -- each test drives a whole path and checks the
facts that path is for. Everything runs offline, so no test loads an encoder or opens a socket.
"""

import pytest

from leela.blocks.memory.memory import GLOBAL, Memory, memory_shelf, safe_shelf


@pytest.fixture
def mem(tmp_path, monkeypatch):
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    return Memory(shelf='my-repo', path=tmp_path/'vault.db', offline=True)


def _doc_ids(m): return [d.get('doc_id') or d.get('id') for d in m.documents()]


def test_a_folder_name_becomes_a_shelf_a_hyphen_cannot_break(tmp_path):
    """A shelf is a table-name prefix, so the name reaches raw SQL.

    litesearch's entity resolution has one unquoted statement that a hyphen breaks, and folder
    names carry hyphens and dots routinely -- so sanitising is not cosmetic.
    """
    assert safe_shelf('my-repo') == safe_shelf('My.Repo') == 'my_repo'
    assert safe_shelf('') == safe_shelf(None) == safe_shelf('--') == 'main'
    assert memory_shelf('/tmp/some-project') == 'some_project'
    assert memory_shelf(None) == 'main', 'no folder open is the main shelf, not a crash'
    # The global shelf is reserved: a folder that happens to be named `leela` must not land on it.
    assert memory_shelf(f'/tmp/{GLOBAL}') == 'main'


def test_clipped_files_land_in_the_shelf_and_are_retrievable(mem, tmp_path):
    (tmp_path/'one.md').write_text('# Retrieval\n\nDurable notes about recall and ranking.\n')
    (tmp_path/'two.md').write_text('# Ranking\n\nA second document, on ordering results.\n')
    rows = mem.clip([tmp_path/'one.md', tmp_path/'two.md'])
    assert len(rows) == 2 and 'clipped 2' in mem.note

    shelves = mem.shelves()
    assert [s['store'] for s in shelves] == ['my_repo'], 'the sanitised name, not the folder name'
    assert shelves[0]['docs'] == 2
    assert len(mem.documents()) == 2

    hits = mem.search('recall and ranking')
    assert hits and hits[0].get('node_id')
    assert mem.read(hits[0]['node_id']).get('text')

    # A ref carries its shelf, because a doc id is content-addressed *per shelf*.
    ref = mem.ref(_doc_ids(mem)[0])
    assert ref.startswith('my_repo|') and len(ref.split('|')) == 2


def test_the_pii_badge_reports_titled_names_and_addresses(mem, tmp_path):
    """What the badge may claim. Titled names and pattern kinds -- not bare names.

    `Ada Lovelace` is deliberately not detected: the name pass is honorific-anchored, so a
    surface that said "no personal information" rather than "none found" would be lying.
    """
    (tmp_path/'minute.md').write_text(
        '# Minute\n\nSigned by Dr Charles Babbage. Deliver to 42 Elm Street, London.\n')
    (tmp_path/'plain.md').write_text('# Plain\n\nAda Lovelace wrote about ranking.\n')
    mem.clip([tmp_path/'minute.md', tmp_path/'plain.md'])

    by_title = {d['title']: (d.get('doc_id') or d.get('id')) for d in mem.documents()}
    minute = mem.pii(by_title['minute'])
    assert minute['has_pii'] and minute['scanned_ner'] is True
    assert set(minute['kinds']) == {'person', 'address'}

    plain = mem.pii(by_title['plain'])
    assert not plain['has_pii'], 'a bare name is not found, which is why the badge says "found"'
    assert plain['scanned_ner'] is True, 'and it must still say that it looked'


def test_a_noisy_judgement_survives_re_ingesting_the_document(mem, tmp_path):
    "`doc_marks` is keyed (doc_id, store) outside the shelf prefix, so re-adding cannot erase it."
    (tmp_path/'changelog.md').write_text('# Changelog\n\n## 1.0\n\nInitial release of the thing.\n')
    mem.clip([tmp_path/'changelog.md'])
    did = _doc_ids(mem)[0]

    assert mem.mark_noisy(did, reason='changelog')['noisy'] == 1
    mem.clip([tmp_path/'changelog.md'], force=True)
    assert mem._open().marks(did).get('noisy'), 'the judgement outlived the document'

    assert mem.mark_noisy(did, noisy=False)['noisy'] == 0
    # The ranker needs a corpus to have an opinion; on two documents it returns nothing rather
    # than raising, which is what keeps the tidy surface honest on a new workspace.
    assert isinstance(mem.noisy_candidates(), list)


def test_a_watch_is_a_cadence_and_polling_runs_what_is_due(mem):
    "A recurring job is a watch row. `remind` keeps this off the network."
    w = mem.watch('review the minute', action='remind', every='1d')
    assert w['action'] == 'remind' and w['every'] == 86400.0

    assert len(mem.watches()) == 1
    got = mem.poll()
    assert got['checked'] == 1 and got['ran'] == 1

    mem.unwatch(w['id'])
    assert mem.watches() == []


def test_a_url_watch_forces_a_refetch_or_it_would_never_refresh(mem, monkeypatch):
    """A page is content-addressed on `source|title`, so an unchanged URL is "already ingested".

    Without `force`, a watch on a page that *did* change reports a skip for ever. Asserted on the
    stored params rather than by fetching, so the test stays offline.
    """
    for action in ('url', 'arxiv', 'youtube'):
        w = mem.watch(f'https://example.com/{action}', action=action, every='6h')
        assert w['params'].get('force') is True, f'{action} must refetch'
        mem.unwatch(w['id'])
    w = mem.watch('think about it', action='remind', every='6h')
    assert 'force' not in (w['params'] or {}), 'a reminder has nothing to refetch'
