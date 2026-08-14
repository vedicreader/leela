"""Several vaults, who may write to each, and reading a vault rather than only writing to it.

Offline throughout: no encoder is loaded and no socket is opened.
"""

import json

import pytest

from leela.blocks.memory.memory import Memory
from leela.blocks.memory.vaults import WORKSPACE, VaultRef, Vaults


@pytest.fixture
def mem(tmp_path, monkeypatch):
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    m = Memory(shelf='proj', path=tmp_path/'vault.db', offline=True)
    (tmp_path/'notes.md').write_text('# Ranking\n\nDurable notes about recall and ranking.\n' * 3)
    (tmp_path/'minute.md').write_text('# Minute\n\nSigned by Dr Charles Babbage, ada@example.com, 555-123-4567.\n')
    return m


@pytest.fixture
def vaults(tmp_path, monkeypatch):
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    return Vaults(path=tmp_path/'vaults.json', workspace_vault=tmp_path/'own.db')


# -- the registry -------------------------------------------------------------

def test_leelas_own_vault_is_always_first_and_cannot_be_detached(vaults, tmp_path):
    """The workspace vault is not a registry row a file may redefine or remove.

    Its location comes from the workspace, so a stale or hostile `vaults.json` naming a different
    path for it would silently move where leela writes.
    """
    assert vaults.active.name == WORKSPACE and vaults.active.writable
    with pytest.raises(ValueError, match='cannot be detached'): vaults.detach(WORKSPACE)

    (tmp_path/'vaults.json').write_text(json.dumps({'active': WORKSPACE,
        'vaults': [{'name': WORKSPACE, 'path': '/somewhere/else.db', 'access': 'admin'}]}))
    again = Vaults(path=tmp_path/'vaults.json', workspace_vault=tmp_path/'own.db')
    assert again.get(WORKSPACE).path.endswith('own.db'), 'the file does not get to say where leela writes'


def test_attaching_needs_a_real_file_and_never_creates_one(vaults, tmp_path):
    "A typo is a typo, not a new empty vault sitting where you meant to point at an existing one."
    with pytest.raises(FileNotFoundError): vaults.attach(tmp_path/'typo.db')
    assert len(vaults) == 1


def test_attach_create_activate_and_detach_round_trip(vaults, tmp_path, monkeypatch):
    made = vaults.create(tmp_path/'research'/'vault.db', name='research')
    assert made.exists and made.access == 'admin', 'a vault you made is yours'

    other = Memory(shelf='main', path=tmp_path/'peer.db', offline=True)
    other._open()                                    # a peer tool's vault, already on disk
    peer = vaults.attach(tmp_path/'peer.db', name='chitragupta')
    assert peer.access == 'read' and not peer.agent_writable, 'an attached vault is read-only until asked'
    assert vaults.attach(tmp_path/'peer.db').name == 'chitragupta', 'attaching twice is not two vaults'

    assert vaults.activate('research').name == 'research' and vaults.active.name == 'research'
    reloaded = Vaults(path=tmp_path/'vaults.json', workspace_vault=tmp_path/'own.db')
    assert reloaded.active.name == 'research', 'the choice outlives the process'
    assert {r.name for r in reloaded} == {WORKSPACE, 'research', 'chitragupta'}

    vaults.detach('chitragupta')
    assert (tmp_path/'peer.db').is_file(), 'detaching forgets a vault, it does not delete one'


def test_a_name_collision_suffixes_rather_than_replacing_a_vault(vaults, tmp_path):
    "Two folders both called `vault` must not silently become one registry entry."
    for i in (1, 2):
        p = tmp_path/f'v{i}'/'vault.db'
        Memory(shelf='main', path=p, offline=True)._open()
        vaults.attach(p, name='shared')
    assert sorted(r.name for r in vaults if r.name != WORKSPACE) == ['shared', 'shared_2']


def test_the_agent_can_never_write_where_the_person_cannot(vaults, tmp_path):
    """`agent` is a narrowing of `access`, not a second opinion about it.

    Turning it on for a read-only vault is refused outright rather than stored and ignored, and
    dropping a vault back to read-only takes the agent's write access with it.
    """
    Memory(shelf='main', path=tmp_path/'peer.db', offline=True)._open()
    vaults.attach(tmp_path/'peer.db', name='peer')
    with pytest.raises(ValueError, match='read-only'): vaults.set_agent('peer', True)

    vaults.set_access('peer', 'admin')
    assert vaults.set_agent('peer', True).agent_writable
    assert not vaults.set_access('peer', 'read').agent_writable, 'the agent loses it with the user'


def test_a_bad_registry_costs_the_file_and_not_the_session(vaults, tmp_path):
    "A registry leela cannot parse, or one row of it, must not take the rest of the vaults with it."
    (tmp_path/'vaults.json').write_text('{"vaults": [')
    corrupt = Vaults(path=tmp_path/'vaults.json', workspace_vault=tmp_path/'own.db')
    assert corrupt.active.name == WORKSPACE and 'could not read' in corrupt.note

    Memory(shelf='main', path=tmp_path/'peer.db', offline=True)._open()
    (tmp_path/'vaults.json').write_text(json.dumps({'active': 'gone', 'vaults': [
        {'name': 'broken'},                                                    # no path at all
        {'name': 'fine', 'path': str(tmp_path/'peer.db'), 'unknown_key': 1}]}))
    v = Vaults(path=tmp_path/'vaults.json', workspace_vault=tmp_path/'own.db')
    assert {r.name for r in v} == {WORKSPACE, 'fine'}
    assert v.active.name == WORKSPACE, 'an active vault the file no longer lists falls back'


def test_a_vault_whose_file_has_gone_is_not_silently_recreated(vaults, tmp_path):
    """Opening a vault creates it, so a deleted or unmounted peer has to be refused.

    Otherwise a vanished peer vault comes back as a new empty one, attached and apparently fine.
    """
    Memory(shelf='main', path=tmp_path/'peer.db', offline=True)._open()
    vaults.attach(tmp_path/'peer.db', name='peer')
    (tmp_path/'peer.db').unlink()
    with pytest.raises(FileNotFoundError): vaults.memory('peer')
    assert not (tmp_path/'peer.db').exists(), 'refused, not remade'


def test_one_file_is_one_vault_however_you_spell_the_path(vaults, tmp_path):
    "A second name for the same file would be two rows disagreeing about who may write to it."
    Memory(shelf='main', path=tmp_path/'peer.db', offline=True)._open()
    vaults.attach(tmp_path/'peer.db', name='peer')
    (tmp_path/'link.db').symlink_to(tmp_path/'peer.db')
    assert vaults.attach(tmp_path/'link.db', name='other').name == 'peer'
    assert len(vaults) == 2


def test_each_vault_gets_one_memory_and_they_are_not_shared(vaults, tmp_path):
    "A second `Memory` on one file would open the same database twice."
    vaults.create(tmp_path/'r'/'vault.db', name='research')
    assert vaults.memory('research') is vaults.memory('research')
    assert vaults.memory('research') is not vaults.memory(WORKSPACE)
    with pytest.raises(KeyError): vaults.memory('nope')


# -- reading a vault ----------------------------------------------------------

def test_documents_and_search_reach_every_shelf_and_say_which(mem, tmp_path):
    "One query has to answer about the vault, not about whichever shelf happens to be current."
    mem.clip([tmp_path/'notes.md'])
    mem.clip([tmp_path/'minute.md'], shelf='archive')

    docs = mem.all_documents()
    assert {d['title'] for d in docs} == {'notes', 'minute'}
    assert {d['title']: d['shelf'] for d in docs} == {'notes': 'proj', 'minute': 'archive'}

    hits = mem.search_all('ranking')
    assert hits and all(h.get('shelf') for h in hits), 'a hit that cannot say where it came from is not openable'


def test_a_document_opens_with_its_header_tree_and_sections(mem, tmp_path):
    """`sections` is the flat rail a reader draws; `toc` keeps vishalakshi's nested shape.

    Every section row must carry a `node_id`, because that is the only thing that can be clicked.
    """
    doc_id = mem.clip([tmp_path/'notes.md'])[0]['doc_id']
    assert mem.document(doc_id)['title'] == 'notes'
    rows = mem.sections(doc_id)
    assert rows and all(r['node_id'] for r in rows)
    assert rows[0]['depth'] == 0, 'the tree flattens root-first'
    assert 'ranking' in mem.shelf_read(rows[0]['node_id']).get('text', '').lower()


def test_moving_a_document_between_shelves_carries_its_text(mem, tmp_path):
    doc_id = mem.clip([tmp_path/'notes.md'])[0]['doc_id']
    out = mem.move(doc_id, 'archive')
    assert out['moved_to'] == 'archive'
    titles = {(d['shelf'], d['title']) for d in mem.all_documents()}
    assert ('archive', 'notes') in titles and ('proj', 'notes') not in titles


def test_an_empty_shelf_can_be_dropped_and_a_full_one_cannot(mem, tmp_path):
    mem.clip([tmp_path/'notes.md'], shelf='archive')
    with pytest.raises(ValueError, match='still holds'): mem.drop_shelf('archive')
    with pytest.raises(ValueError, match='in use'): mem.drop_shelf('proj')

    mem.move(mem.all_documents(shelves=['archive'])[0]['doc_id'], 'keep', shelf='archive')
    assert mem.drop_shelf('archive')['shelf'] == 'archive', 'emptied, so it goes'
    assert 'archive' not in [s['store'] for s in mem.shelves()]


def test_a_workspace_with_no_project_open_lists_each_document_once(mem, tmp_path):
    """One shelf must not answer under two names.

    `shelves()` reports the unprefixed store as `store` while a shelf argument calls it `main`,
    so with no project open the default shelf was walked twice and every row came back doubled.
    """
    m = Memory(shelf='main', path=tmp_path/'noproject.db', offline=True)
    m.clip([tmp_path/'notes.md'])
    assert [d['shelf'] for d in m.all_documents()] == ['main']
    assert [d['shelf'] for d in m.all_documents(shelves=['store'])] == ['main'], 'either name reaches the one shelf'


def test_pii_evidence_matches_the_badge_and_an_override_is_durable(mem, tmp_path):
    """The evidence list and the badge must agree, and a judgement must survive re-ingestion.

    Both were wrong first time: the scan ran without `ner`, so it found the email but not the
    titled name the badge claims to cover; and the override was written to `meta`, where
    `Vault.pii` does not read it and the next clip erases it.
    """
    doc_id = mem.clip([tmp_path/'minute.md'])[0]['doc_id']
    assert {e['kind'] for e in mem.pii_evidence(doc_id)} >= {'person', 'email', 'phone'}
    assert all(e['page'] >= 1 for e in mem.pii_evidence(doc_id)), 'pages are 1-based for a reader'

    mem.mark_not_pii(doc_id, reason='fictional')
    report = mem.pii(doc_id)
    assert not report['has_pii'] and report['detected'], 'overridden, not undetected'
    mem.clip([tmp_path/'minute.md'], force=True)
    assert not mem.pii(doc_id)['has_pii'], 'the judgement outlived re-ingestion'

    mem.mark_not_pii(doc_id, clear=False)
    assert mem.pii(doc_id)['has_pii'], 'automatic detection comes back'


def test_every_document_row_carries_one_id_name(mem, tmp_path):
    """`sources()` says `id`, `add`/`clip` say `doc_id`. A browser holding both should not care.

    The reader passes whatever it has straight back to `/vault/doc`, so a row missing `doc_id`
    is a row that cannot be opened.
    """
    clipped = mem.clip([tmp_path/'notes.md'])[0]
    row = mem.all_documents()[0]
    assert row['doc_id'] == clipped['doc_id'] == row['id']
