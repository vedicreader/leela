"Memory: the vault, its shelves, its routes, and the migration into it."

from types import SimpleNamespace
import json
from leela.blocks.memory.memory import GLOBAL, Memory
from leela.blocks.research.research import Doc, Research
from leela.blocks.fs.fs import Sandbox
import pytest
from leela.blocks.memory.memory import memory_shelf, safe_shelf
from leela.blocks.memory.vaults import WORKSPACE, Vaults
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.workspace import Workspace
import sqlite3
from leela.migrate_memory import migrate, read_old

def _mem(tmp_path, shelf='proj'):
    return Memory(shelf=shelf, path=tmp_path/'vault.db', offline=True)

def test_remembered_page_has_a_tree_and_searchable_sections(tmp_path):
    mem = _mem(tmp_path)
    doc = Doc(title='Agent memory notes', url='https://example.com/memory', kind='page', text='''
# Memory systems

Simple structured memory can outperform elaborate retrieval.

## Evaluation

Measure recall accuracy and latency for every agent memory design.
''')
    saved = mem.remember(doc)
    assert saved['nodes'] >= 2 and saved['chunks'] >= 1
    assert mem.status()['documents'] == 1
    toc = mem.toc(saved['doc_id'])
    assert toc[0]['title'] == 'Agent memory notes'
    hits = mem.search('recall accuracy agent memory')
    assert hits and hits[0].get('node_id')
    section = mem.read(hits[0]['node_id'])
    assert 'recall' in section.get('text', '').lower() or 'memory' in section.get('text', '').lower()
    assert mem.remember(doc)['skipped']
    doc.text += '\n\n## Update\n\nNew durable memory material.'
    refreshed = mem.remember(doc)
    assert refreshed['nodes'] >= 2 and mem.status()['documents'] == 1

def test_research_automatically_remembers_sources_and_query_brief(monkeypatch, tmp_path):
    mem = _mem(tmp_path)
    research = Research(Sandbox([tmp_path]), memory=mem)
    body = '# Findings\n\nAgent memory evidence ' * 100
    fake = SimpleNamespace(research=lambda q, n=5, **kw: {
        'query': q,
        'sources': [
            {'title': 'One', 'href': 'https://one.example', 'md': body},
            {'title': 'Two', 'href': 'https://two.example', 'md': body},
        ],
        'digest': f'## One\nhttps://one.example\n\n{body}\n\n---\n\n## Two\nhttps://two.example\n\n{body}',
        'dropped': [], 'plan': [q],
    })
    monkeypatch.setattr(research, '_fossick', lambda: fake)
    docs, digest = research.dig('agent memory evidence', n=2)
    assert len(docs) == 2 and digest
    remembered = mem.documents()
    assert {row['kind'] for row in remembered} == {'page', 'research'}
    assert any(row['title'] == 'Research: agent memory evidence' for row in remembered)

def test_research_can_read_without_adding_to_memory(monkeypatch, tmp_path):
    mem = _mem(tmp_path)
    research = Research(Sandbox([tmp_path]), memory=mem)
    fake = SimpleNamespace(fetch=lambda *a, **k: object(),
                           to_md=lambda *a, **k: '# Private result\n\nDo not retain this page. ' * 60)
    monkeypatch.setattr(research, '_fossick', lambda: fake)
    doc = research.read('https://sensitive.example/result', remember=False)
    assert doc and not doc.memory_id
    assert mem.status()['documents'] == 0

def test_memory_can_forget_a_document_and_all_its_sections(tmp_path):
    mem = _mem(tmp_path)
    saved = mem.remember(Doc('Temporary', 'https://temporary.example', '# Note\n\nForget this research.'))
    assert mem.forget(saved['doc_id'])
    assert mem.status()['documents'] == 0 and mem.status()['chunks'] == 0

def test_memory_can_purge_selected_or_everything(tmp_path):
    mem = _mem(tmp_path)
    one = mem.remember(Doc('Bad result', 'https://bad.example', '# Bad\n\nIrrelevant result.'))
    mem.remember(Doc('Useful result', 'https://good.example', '# Good\n\nUseful result.'))
    assert mem.purge([one['doc_id']]) == 1
    assert [d['title'] for d in mem.documents()] == ['Useful result']
    assert mem.purge() == 1 and mem.status()['documents'] == 0

def test_edited_conversation_state_round_trips_through_memory(tmp_path):
    mem = _mem(tmp_path)
    state = '# Goal\n\nKeep the agent focused.\n\n# Next steps\n\nInspect before editing.'
    saved = mem.remember_agent_state('Focused implementation', state, {'session': 'agent_test'})
    states = mem.agent_states()
    assert saved and states[0]['kind'] == 'agent-state'
    assert states[0]['title'] == 'Focused implementation'
    loaded = mem.agent_state_text(saved['doc_id'])
    assert 'Keep the agent focused' in loaded and 'Inspect before editing' in loaded
    assert mem._agent().name == GLOBAL
    assert not any(d['kind'] == 'agent-state' for d in mem.documents())

def test_agent_memory_notes_can_be_created_edited_and_deleted(tmp_path):
    mem = _mem(tmp_path)
    authored = '# Decision\n\n- Keep the public API stable.\n\n```python\nvalue = 1\n```\n'
    first = mem.remember_agent_note('Architecture', authored)
    note_id = first['doc_id']
    assert mem.agent_notes()[0]['title'] == 'Architecture'
    assert mem.exact_text(note_id) == authored.strip()
    edited = mem.remember_agent_note('Architecture rules', '# Decision\n\nKeep compatibility.', note_id)
    assert edited['doc_id'] != note_id
    assert [note['title'] for note in mem.agent_notes()] == ['Architecture rules']
    assert mem.forget(edited['doc_id'])
    assert mem.agent_notes() == []

def test_agent_notes_do_not_leak_into_project_documents(tmp_path):
    mem = _mem(tmp_path)
    mem.remember(Doc('Project page', 'https://project.example', '# Project\n\nScoped reading.'))
    mem.remember_agent_note('Private', '# Note\n\nGlobal only.')
    assert [d['title'] for d in mem.documents()] == ['Project page']
    assert [d['title'] for d in mem.agent_notes()] == ['Private']

def test_workspace_persists_the_active_agent_state(tmp_path):
    state_file = tmp_path/'workspace.json'
    ws = Workspace(roots=[tmp_path]); ws.agent_state = '# Goal\n\nStart from reviewed context.'; ws.save(state_file)
    restored = Workspace.load(state_file)
    assert restored.agent_state == ws.agent_state

def test_workspace_persists_per_surface_memory_routing(tmp_path):
    path = tmp_path/'workspace.json'; ws = Workspace(roots=[tmp_path])
    ws.agent_memory_selection = {'agent': ['one'], 'inline': ['one', 'two'], 'completion': ['two']}
    ws.save(path); restored = Workspace.load(path)
    assert restored.agent_memory_selection == ws.agent_memory_selection

def test_workspace_load_restores_a_remembered_agent_state_for_the_project(tmp_path, monkeypatch):
    root = tmp_path/'project'; root.mkdir()
    monkeypatch.setattr(Memory, 'agent_states', lambda self: [{
        'id': 'remembered', 'meta': {'agent': {'roots': [str(root)]}}}])
    monkeypatch.setattr(Memory, 'agent_state_text', lambda self, doc_id: '# Goal\n\nFollow this project.')
    state = tmp_path/'workspace.json'
    state.write_text(json.dumps({'roots': [str(root)]}))
    restored = Workspace.load(state)
    assert restored.agent_state_layers['task']['source'] == 'memory'
    assert 'Follow this project' in restored.agent_state

def test_clusters_report_why_a_small_memory_cannot_form_topics(tmp_path):
    mem = _mem(tmp_path)
    mem.remember(Doc('One note', 'https://one.example', '# Note\n\nA small memory entry.'))
    result = mem.clusters()
    assert 'note' in result and 'clusters' in result

def test_context_never_pulls_other_shelves_or_code(tmp_path, monkeypatch):
    mem = _mem(tmp_path)
    mem.remember(Doc('Here', 'https://here.example', '# Here\n\nProject-local evidence about kernels.'))
    seen = {}
    v = mem._open()
    real = v.context
    monkeypatch.setattr(v, 'context', lambda q, **kw: seen.update(kw) or real(q, **kw))
    out = mem.context('kernels')
    assert seen.get('shelves') == 0 and seen.get('code') == 0
    assert out['query'] == 'kernels'

@pytest.fixture
def mem_vault(tmp_path, monkeypatch):
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    return Memory(shelf='my-repo', path=tmp_path/'vault.db', offline=True)

def _ids(m): return [d.get('doc_id') or d.get('id') for d in m.documents()]

def test_a_folder_name_becomes_a_shelf_a_hyphen_cannot_break(tmp_path):
    "A shelf is a table-name prefix, so the name reaches raw SQL."
    assert safe_shelf('my-repo') == safe_shelf('My.Repo') == 'my_repo'
    assert safe_shelf('') == safe_shelf(None) == safe_shelf('--') == 'main'
    assert memory_shelf('/tmp/some-project') == 'some_project'
    assert memory_shelf(None) == 'main', 'no folder open is the main shelf, not a crash'
    assert memory_shelf(f'/tmp/{GLOBAL}') == 'main', 'the global shelf is reserved'

def test_a_clip_lands_is_judged_and_the_judgement_outlives_it(mem_vault, tmp_path):
    "One walk through the whole surface: ingest, retrieve, report, judge, re-ingest."
    (tmp_path/'notes.md').write_text('# Retrieval\n\nDurable notes about recall and ranking.\n')
    (tmp_path/'minute.md').write_text(
        '# Minute\n\nSigned by Dr Charles Babbage. Deliver to 42 Elm Street, London.\n')
    (tmp_path/'plain.md').write_text('# Plain\n\nAda Lovelace wrote about ranking.\n')
    assert len(mem_vault.clip(list(tmp_path.glob('*.md')))) == 3
    shelves = mem_vault.shelves()
    assert [s['store'] for s in shelves] == ['my_repo'], 'the sanitised name, not the folder name'
    assert shelves[0]['docs'] == 3
    hits = mem_vault.search('recall and ranking')
    assert hits and mem_vault.read(hits[0]['node_id']).get('text')
    by_title = {d['title']: (d.get('doc_id') or d.get('id')) for d in mem_vault.documents()}
    minute = mem_vault.pii(by_title['minute'])
    assert minute['has_pii'] and set(minute['kinds']) == {'person', 'address'}
    plain = mem_vault.pii(by_title['plain'])
    assert not plain['has_pii'], 'a bare name is not found, which is why the badge says "found"'
    assert plain['scanned_ner'], 'and it must still say that it looked'
    assert mem_vault.ref(by_title['notes']).startswith('my_repo|')
    did = by_title['minute']
    assert mem_vault.mark_noisy(did, reason='changelog')['noisy'] == 1
    mem_vault.clip([tmp_path/'minute.md'], force=True)
    assert mem_vault._open().marks(did).get('noisy'), 'the judgement outlived the document'
    assert mem_vault.mark_noisy(did, noisy=False)['noisy'] == 0
    assert isinstance(mem_vault.noisy_candidates(), list), 'no opinion on a tiny corpus, but no crash'

def test_a_cadence_is_a_watch_and_a_url_watch_forces_a_refetch(mem_vault):
    "`remind` keeps this offline; the `force` assertion is read off the stored params."
    w = mem_vault.watch('review the minute', action='remind', every='1d')
    assert w['every'] == 86400.0 and 'force' not in (w['params'] or {})
    assert len(mem_vault.watches()) == 1
    got = mem_vault.poll()
    assert got['checked'] == 1 and got['ran'] == 1
    mem_vault.unwatch(w['id'])
    assert mem_vault.watches() == []
    for action in ('url', 'arxiv', 'youtube'):
        w = mem_vault.watch(f'https://example.com/{action}', action=action, every='6h')
        assert w['params'].get('force') is True, f'{action} must refetch'
        mem_vault.unwatch(w['id'])

def test_a_clips_pii_report_covers_what_that_clip_wrote(mem_vault, tmp_path):
    "The summary is about the documents this job clipped, not about the shelf."
    from leela.blocks.vault.clip import _pii_summary
    (tmp_path/'cv.md').write_text('# CV\n\nDr Charles Babbage, ada@example.com, 555-123-4567.\n')
    (tmp_path/'clean.md').write_text('# Notes\n\nRanking and recall, no one in particular.\n')
    rows = {r['title']: r['doc_id'] for r in mem_vault.clip(sorted(tmp_path.glob('*.md')))}
    clean = _pii_summary(mem_vault, [rows['clean']], mem_vault.shelf_name)
    assert clean['documents'] == [] and clean['kinds'] == {}, 'the CV is in the shelf, not in this clip'
    cv = _pii_summary(mem_vault, [rows['cv']], mem_vault.shelf_name)
    assert cv['documents'] == [mem_vault.ref(rows['cv'], mem_vault.shelf_name)]
    assert set(cv['kinds']) >= {'email', 'phone'}

def test_purge_attempts_each_document_once(mem_vault, tmp_path):
    "The three listings overlap; a document whose forget fails must not be retried per duplicate."
    (tmp_path/'a.md').write_text('# A\n\nDurable prose about ranking.\n')
    mem_vault.clip([tmp_path/'a.md'])
    doc_id = (mem_vault.documents() or [{}])[0]['id']
    tried = []
    mem_vault.forget = lambda i: (tried.append(i), False)[1]
    assert mem_vault.purge() == 0
    assert tried.count(doc_id) == 1, 'one attempt per document, however many listings name it'

@pytest.fixture
def mem_vaults(tmp_path, monkeypatch):
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    m = Memory(shelf='proj', path=tmp_path/'vault.db', offline=True)
    (tmp_path/'notes.md').write_text('# Ranking\n\nDurable notes about recall and ranking.\n' * 3)
    (tmp_path/'minute.md').write_text('# Minute\n\nSigned by Dr Charles Babbage, ada@example.com, 555-123-4567.\n')
    return m

@pytest.fixture
def vaults(tmp_path, monkeypatch):
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    return Vaults(path=tmp_path/'vaults.json', workspace_vault=tmp_path/'own.db')

def test_leelas_own_vault_is_always_first_and_cannot_be_detached(vaults, tmp_path):
    "The workspace vault is not a registry row a file may redefine or remove."
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
    other._open()
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
    "`agent` is a narrowing of `access`, not a second opinion about it."
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
        {'name': 'broken'},
        {'name': 'fine', 'path': str(tmp_path/'peer.db'), 'unknown_key': 1}]}))
    v = Vaults(path=tmp_path/'vaults.json', workspace_vault=tmp_path/'own.db')
    assert {r.name for r in v} == {WORKSPACE, 'fine'}
    assert v.active.name == WORKSPACE, 'an active vault the file no longer lists falls back'

def test_a_vault_whose_file_has_gone_is_not_silently_recreated(vaults, tmp_path):
    "Opening a vault creates it, so a deleted or unmounted peer has to be refused."
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

def test_documents_and_search_reach_every_shelf_and_say_which(mem_vaults, tmp_path):
    "One query has to answer about the vault, not about whichever shelf happens to be current."
    mem_vaults.clip([tmp_path/'notes.md'])
    mem_vaults.clip([tmp_path/'minute.md'], shelf='archive')
    docs = mem_vaults.all_documents()
    assert {d['title'] for d in docs} == {'notes', 'minute'}
    assert {d['title']: d['shelf'] for d in docs} == {'notes': 'proj', 'minute': 'archive'}
    hits = mem_vaults.search_all('ranking')
    assert hits and all(h.get('shelf') for h in hits), 'a hit that cannot say where it came from is not openable'

def test_a_document_opens_with_its_header_tree_and_sections(mem_vaults, tmp_path):
    "`sections` is the flat rail a reader draws; `toc` keeps vishalakshi's nested shape."
    doc_id = mem_vaults.clip([tmp_path/'notes.md'])[0]['doc_id']
    assert mem_vaults.document(doc_id)['title'] == 'notes'
    rows = mem_vaults.sections(doc_id)
    assert rows and all(r['node_id'] for r in rows)
    assert rows[0]['depth'] == 0, 'the tree flattens root-first'
    assert 'ranking' in mem_vaults.shelf_read(rows[0]['node_id']).get('text', '').lower()

def test_moving_a_document_between_shelves_carries_its_text(mem_vaults, tmp_path):
    doc_id = mem_vaults.clip([tmp_path/'notes.md'])[0]['doc_id']
    out = mem_vaults.move(doc_id, 'archive')
    assert out['moved_to'] == 'archive'
    titles = {(d['shelf'], d['title']) for d in mem_vaults.all_documents()}
    assert ('archive', 'notes') in titles and ('proj', 'notes') not in titles

def test_an_empty_shelf_can_be_dropped_and_a_full_one_cannot(mem_vaults, tmp_path):
    mem_vaults.clip([tmp_path/'notes.md'], shelf='archive')
    with pytest.raises(ValueError, match='still holds'): mem_vaults.drop_shelf('archive')
    with pytest.raises(ValueError, match='in use'): mem_vaults.drop_shelf('proj')
    mem_vaults.move(mem_vaults.all_documents(shelves=['archive'])[0]['doc_id'], 'keep', shelf='archive')
    assert mem_vaults.drop_shelf('archive')['shelf'] == 'archive', 'emptied, so it goes'
    assert 'archive' not in [s['store'] for s in mem_vaults.shelves()]

def test_a_workspace_with_no_project_open_lists_each_document_once(mem_vaults, tmp_path):
    "One shelf must not answer under two names."
    m = Memory(shelf='main', path=tmp_path/'noproject.db', offline=True)
    m.clip([tmp_path/'notes.md'])
    assert [d['shelf'] for d in m.all_documents()] == ['main']
    assert [d['shelf'] for d in m.all_documents(shelves=['store'])] == ['main'], 'either name reaches the one shelf'

def test_pii_evidence_matches_the_badge_and_an_override_is_durable(mem_vaults, tmp_path):
    "The evidence list and the badge must agree, and a judgement must survive re-ingestion."
    doc_id = mem_vaults.clip([tmp_path/'minute.md'])[0]['doc_id']
    assert {e['kind'] for e in mem_vaults.pii_evidence(doc_id)} >= {'person', 'email', 'phone'}
    assert all(e['page'] >= 1 for e in mem_vaults.pii_evidence(doc_id)), 'pages are 1-based for a reader'
    mem_vaults.mark_not_pii(doc_id, reason='fictional')
    report = mem_vaults.pii(doc_id)
    assert not report['has_pii'] and report['detected'], 'overridden, not undetected'
    mem_vaults.clip([tmp_path/'minute.md'], force=True)
    assert not mem_vaults.pii(doc_id)['has_pii'], 'the judgement outlived re-ingestion'
    mem_vaults.mark_not_pii(doc_id, clear=False)
    assert mem_vaults.pii(doc_id)['has_pii'], 'automatic detection comes back'

def test_a_retrieval_policy_masks_or_withholds_what_the_model_would_have_read(mem_vaults, tmp_path):
    """The gate is on the retrieval, not on the model: `off` hands the text over, `redact` masks the
    identifiers in it, `refuse` hands back a stand-in saying what was held. A person browsing their
    own vault is never gated; only what a retrieval returns is."""
    mem_vaults.clip([tmp_path/'minute.md'])
    node = mem_vaults.search('Babbage signed the minute')[0]['node_id']
    plain = mem_vaults.read(node)['text']
    assert 'ada@example.com' in plain, 'off is the default, and off is what it says'
    assert 'ada@example.com' not in mem_vaults.read(node, pii='redact')['text']
    withheld = mem_vaults.read(node, pii='refuse')['text']
    assert 'ada@example.com' not in withheld and 'withheld' in withheld
    hits = mem_vaults.search('Babbage signed the minute', pii='redact')
    assert hits and not any('ada@example.com' in str(h.get('snippet') or '') for h in hits)
    ctx = mem_vaults.context('who signed the minute', pii='refuse')
    assert not any('ada@example.com' in str(r.get('text') or '') for r in ctx['results'])

def test_an_unknown_retrieval_policy_is_refused_rather_than_read_as_off(mem_vaults, tmp_path):
    "Reading a typo as `off` would turn the safest-looking spelling into no gate at all."
    from leela.blocks.memory.memory import pii_gate
    assert pii_gate(None) == pii_gate('') == pii_gate('OFF') == 'off'
    with pytest.raises(ValueError, match='pii must be one of'): pii_gate('redct')
    mem_vaults.clip([tmp_path/'minute.md'])
    with pytest.raises(ValueError): mem_vaults.context('who signed it', pii='refuze')

def test_a_document_can_be_forced_private_and_the_gate_honours_it(mem_vaults, tmp_path):
    """`mark_not_pii` was the only override, so a document arithmetic cannot read as private -- a
    bare name, a loose address, a scanned page -- had no way to be treated as one."""
    doc_id = mem_vaults.clip([tmp_path/'notes.md'])[0]['doc_id']
    assert not mem_vaults.pii(doc_id)['has_pii'], 'nothing in it is a pattern'
    mem_vaults.mark_pii(doc_id, reason='a colleague is named in it')
    report = mem_vaults.pii(doc_id)
    assert report['has_pii'] and report['override'] == 'force' and not report['detected']
    assert 'ranking' not in mem_vaults.search('recall and ranking', pii='refuse')[0].get('snippet', '').lower()
    mem_vaults.mark_pii(doc_id, force=False)
    assert not mem_vaults.pii(doc_id)['has_pii'], 'automatic detection comes back'

def test_every_document_row_carries_one_id_name(mem_vaults, tmp_path):
    "`sources()` says `id`, `add`/`clip` say `doc_id`. A browser holding both should not care."
    clipped = mem_vaults.clip([tmp_path/'notes.md'])[0]
    row = mem_vaults.all_documents()[0]
    assert row['doc_id'] == clipped['doc_id'] == row['id']

@pytest.fixture
def proj(tmp_path):
    (tmp_path/'notes.md').write_text('# Ranking\n\nDurable notes about recall and ranking.\n' * 3)
    (tmp_path/'minute.md').write_text('# Minute\n\nSigned by Dr Charles Babbage, ada@example.com.\n')
    return tmp_path

@pytest.fixture
def ws(proj, monkeypatch, tmp_path_factory):
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    w = Workspace(roots=[proj])
    w.vaults.file = tmp_path_factory.mktemp('reg')/'vaults.json'
    return w

def test_a_vault_is_browsable_readable_and_searchable(ws, proj):
    "Browse, open, read a section, search. Each step has to hand the next one what it needs."
    with TestClient(ide_app(ws)) as c:
        ws.memory.clip([proj/'notes.md'])
        ws.memory.clip([proj/'minute.md'], shelf='archive')
        d = c.get('/vault/documents').json()
        assert {x['title'] for x in d['documents']} == {'notes', 'minute'}
        assert all(x.get('shelf') for x in d['documents']), 'a row that cannot say where it lives cannot be opened'
        assert d['vault']['name'] == WORKSPACE and d['vault']['writable']
        row = next(x for x in d['documents'] if x['title'] == 'notes')
        doc = c.get('/vault/doc', params={'doc': row['doc_id'], 'shelf': row['shelf']}).json()
        assert doc['doc']['title'] == 'notes' and doc['sections']
        assert all(s['node_id'] for s in doc['sections'])
        sec = c.get('/vault/section', params={'node': doc['sections'][0]['node_id'],
                                              'shelf': row['shelf']}).json()
        assert 'ranking' in sec['section'].get('text', '').lower()
        hits = c.get('/vault/search', params={'q': 'ranking'}).json()['hits']
        assert hits and all(h.get('shelf') for h in hits)
        assert c.get('/vault/doc', params={'doc': 'nope'}).status_code == 404
        assert c.get('/vault/section', params={'node': 'nope#9'}).status_code == 404

def test_privacy_travels_with_the_document_and_can_be_overridden(ws, proj):
    "The reader gets the report, the evidence behind it, and the sentence saying what it covers."
    with TestClient(ide_app(ws)) as c:
        doc_id = ws.memory.clip([proj/'minute.md'])[0]['doc_id']
        d = c.get('/vault/doc', params={'doc': doc_id}).json()
        assert d['privacy']['has_pii'] and d['evidence']
        assert {e['kind'] for e in d['evidence']} >= {'person', 'email'}
        assert 'never' in d['covers'], 'the surface must not imply a clean scan means none'
        after = c.post('/vault/not-pii', data={'doc': doc_id, 'reason': 'fictional'}).json()
        assert not after['privacy']['has_pii'] and after['privacy']['detected']
        assert c.get('/vault/doc', params={'doc': doc_id}).json()['evidence'] == [], 'no longer flagged'

def test_a_document_arithmetic_cannot_read_as_private_can_still_be_marked_one(ws, proj):
    "The other half of the override, and the same shape of answer: ok, the fresh report, what it covers."
    with TestClient(ide_app(ws)) as c:
        doc_id = ws.memory.clip([proj/'notes.md'])[0]['doc_id']
        assert not c.get('/vault/doc', params={'doc': doc_id}).json()['privacy']['has_pii']
        marked = c.post('/vault/pii/mark', data={'doc': doc_id, 'reason': 'a colleague is named'}).json()
        assert marked['ok'] and marked['privacy']['has_pii'] and marked['privacy']['override'] == 'force'
        assert 'never' in marked['covers']
        assert c.get('/vault/doc', params={'doc': doc_id}).json()['privacy']['override'] == 'force'
        back = c.post('/vault/pii/mark', data={'doc': doc_id, 'force': False}).json()
        assert not back['privacy']['has_pii'], 'automatic detection comes back'
        assert c.post('/vault/pii/mark', data={'doc': doc_id, 'vault': 'nope'}).status_code in (400, 403)

def test_both_privacy_overrides_have_a_button_in_the_reader_and_reach_their_route():
    """`/vault/pii/mark` shipped as a route with no caller once before, on the branch routes. Draw
    the button in the source and the bundle the app actually serves, and wire it to the route."""
    from pathlib import Path as _P
    root = _P(__file__).resolve().parents[1]/'leela'
    for js in ((root/'blocks'/'vault'/'reader.js').read_text(), (root/'static'/'lee-ide.js').read_text()):
        assert "'/vault/pii/mark'" in js and "'/vault/not-pii'" in js, 'a route nobody can reach'
        assert 'data-vault-pii' in js and 'data-vault-notpii' in js
        assert 'mark personal' in js and 'mark not personal' in js
        assert 'Marked personal' in js, 'a forced document has to say so, not read as a found pattern'

def test_shelves_can_be_managed_and_an_occupied_one_is_not_dropped(ws, proj):
    with TestClient(ide_app(ws)) as c:
        doc_id = ws.memory.clip([proj/'notes.md'])[0]['doc_id']
        assert c.post('/vault/shelf/move', data={'doc': doc_id, 'target': 'archive'}).json()['moved_to'] == 'archive'
        assert {x['shelf'] for x in c.get('/vault/documents').json()['documents']} == {'archive'}
        assert c.post('/vault/shelf/drop', data={'shelf': 'archive'}).status_code == 400, 'it still holds a document'

def test_an_attached_vault_is_read_only_until_you_say_otherwise(ws, tmp_path):
    "The whole point of attaching a peer tool's vault: leela can read it and cannot write to it."
    peer = tmp_path/'peer'/'vault.db'
    Memory(shelf='main', path=peer, offline=True)._open()
    with TestClient(ide_app(ws)) as c:
        attached = c.post('/vault/attach', data={'path': str(peer), 'name': 'peer'}).json()
        assert attached['access'] == 'read' and not attached['agent_writable']
        for path, data in (('/vault/shelf/drop', {'shelf': 'whatever'}),
                           ('/vault/shelf/move', {'doc': 'd1', 'target': 'archive'}),
                           ('/vault/not-pii', {'doc': 'd1'})):
            refused = c.post(path, data={**data, 'vault': 'peer'})
            assert refused.status_code == 403, f'{path}: a refusal is not a malformed request'
            assert 'read-only' in refused.text, path
        assert 'read-only' in c.post('/vault/access', data={'name': 'peer', 'agent': 'true'}).text, \
            'the agent cannot be given write access a person does not have'
        c.post('/vault/access', data={'name': 'peer', 'access': 'admin'})
        assert c.post('/vault/access', data={'name': 'peer', 'agent': 'true'}).json()['agent_writable']
        assert not c.post('/vault/access', data={'name': 'peer', 'access': 'read'}).json()['agent_writable'], \
            'dropping back to read takes the agent with it'
        assert c.post('/vault/activate', data={'name': 'peer'}).json()['name'] == 'peer'
        assert c.get('/vault/list').json()['active'] == 'peer'
        c.post('/vault/detach', data={'name': 'peer'})
        assert c.get('/vault/list').json()['active'] == WORKSPACE, 'detaching the active one falls back'
        assert peer.is_file(), 'detach forgets a vault, it does not delete one'

def test_the_agent_toggle_is_a_boundary_not_a_label(ws, proj):
    "`agent_writable` has to be enforced where the model calls, not only in the panel."
    from leela.blocks.agent.ai import WorkspaceHost
    host = WorkspaceHost(ws)
    doc_id = ws.memory.clip([proj/'notes.md'])[0]['doc_id']
    ws.vaults.set_agent(WORKSPACE, False)
    for call in (lambda: host.memory_forget(doc_id),
                 lambda: host.remember('a note the agent wants to keep'),
                 lambda: host.watch('https://example.com', action='url')):
        with pytest.raises(PermissionError, match='may not write'): call()
    assert host.memory_documents(), 'reading is not gated'
    assert host.memory_sections(doc_id)
    ws.vaults.set_agent(WORKSPACE, True)
    assert host.remember('a note the agent wants to keep')
    assert host.memory_forget(doc_id)

def test_a_vault_document_opens_as_a_tab_with_no_path(ws, proj):
    "A vault tab names a document, as a pdf tab names a file: the client fetches the contents."
    with TestClient(ide_app(ws)) as c:
        doc_id = ws.memory.clip([proj/'notes.md'])[0]['doc_id']
        assert c.post('/vault/open', data={'doc': doc_id, 'title': 'notes'}).status_code == 200
        tab = ws.tabs[ws.active]
        assert tab.kind == 'vault' and tab.path == '' and tab.ref.endswith(f'|{doc_id}')
        assert not tab.private_kernel, 'a document is not something you run'
        st = c.get('/tab/state').json()
        assert st['kind'] == 'vault' and st['doc'] == doc_id and st['title'] == 'notes'
        c.post('/vault/open', data={'doc': doc_id, 'title': 'notes'})
        assert sum(t.kind == 'vault' for t in ws.tabs) == 1, 'opening it twice focuses the tab it already has'

def test_the_panel_lists_vaults_and_documents_you_can_click(ws, proj):
    "The reader is only reachable if something renders a row that opens it."
    with TestClient(ide_app(ws)) as c:
        ws.memory.clip([proj/'notes.md'])
        panel = c.get('/vault/panel').text
        assert 'id="vaultbrowse"' in panel and 'hx-get="/vault/browse"' in panel
        assert 'agent off' in panel or 'agent on' in panel, 'the per-vault agent toggle is on the row'
        docs = c.get('/vault/browse').text
        assert 'leeOpenVaultDoc(' in docs and 'notes' in docs
        assert 'lee-vault-tree' in docs and 'lee-vault-folder' in docs
        hits = c.get('/vault/browse', params={'q': 'ranking'}).text
        assert 'leeOpenVaultDoc(' in hits, 'a hit opens the document it is in'
        assert 'lee-vault-tree' not in hits, 'a query answers with hits, not with the tree'

def test_a_vault_name_browses_it_without_making_it_active(ws, proj):
    "Reading a vault and writing to one are different intentions; only the dot changes writes."
    with TestClient(ide_app(ws)) as c:
        ws.memory.clip([proj/'notes.md'])
        row = c.get('/vault/panel').text
        assert 'hx-get="/vault/browse"' in row and 'lee-vault-open' in row, 'the name is a control'
        assert 'lee-vault-active' in row and '/vault/activate' not in row

def test_browsing_a_vault_scopes_the_search_box_to_it(ws, proj):
    "Swapping only the list would leave the panel's form behind, searching the active vault."
    with TestClient(ide_app(ws)) as c:
        ws.memory.clip([proj/'notes.md'])
        block = c.get('/vault/browse', params={'vault': 'workspace'}).text
        assert 'id="vaultbrowse"' in block
        assert 'name="vault"' in block and 'value="workspace"' in block
        assert 'documents · workspace' in block, 'the legend says which vault is open'

def test_the_tree_keeps_real_folders_and_drops_the_common_chrome(ws, proj):
    "A vault clipped from one deep folder must open on its own folders, not on six of /Users."
    (proj/'docs'/'deep').mkdir(parents=True)
    (proj/'papers').mkdir()
    (proj/'docs'/'a.md').write_text('# A\nalpha\n')
    (proj/'docs'/'deep'/'b.md').write_text('# B\nbeta\n')
    (proj/'papers'/'c.md').write_text('# C\ngamma\n')
    with TestClient(ide_app(ws)) as c:
        ws.memory.clip([proj/'docs'/'a.md', proj/'docs'/'deep'/'b.md', proj/'papers'/'c.md'])
        tree = c.get('/vault/tree').text
        assert '>docs<' in tree and '>papers<' in tree, 'the folders that differ survive'
        for chrome in ('>private<', '>var<', '>folders<', '>T<'):
            assert chrome not in tree, chrome
        shelf = ws.memory.shelf_name
        assert '>deep<' not in tree
        deep = c.get('/vault/tree', params={'open': f'{shelf}|{shelf}/docs'}).text
        assert '>deep<' in deep and 'a.md' in deep

def test_a_document_that_was_never_a_file_has_no_open_file_button(ws, proj):
    with TestClient(ide_app(ws)) as c:
        ws.memory.clip([proj/'notes.md'])
        row = c.get('/vault/browse').text
        assert 'leeOpenVaultFile(' in row, 'a clipped file offers to open the file'
        doc = next(d for d in ws.memory.all_documents() if d.get('source', '').endswith('notes.md'))
        src = c.get('/vault/source', params={'doc': doc['doc_id']}).json()
        assert src['kind'] == 'file' and src['exists'] and src['inside_workspace']

def test_a_source_outside_the_workspace_is_reported_not_read(ws, proj, tmp_path_factory):
    "The fs sandbox refuses paths outside a root, so the answer is `no`, not a way around it."
    outside = tmp_path_factory.mktemp('elsewhere')
    (outside/'far.md').write_text('# Far\n\nfar away\n')
    with TestClient(ide_app(ws)) as c:
        ws.memory.clip([outside/'far.md'])
        doc = next(d for d in ws.memory.all_documents() if d.get('source', '').endswith('far.md'))
        src = c.get('/vault/source', params={'doc': doc['doc_id']}).json()
        assert src['kind'] == 'file' and src['exists'] and not src['inside_workspace']
        assert src['parent'] == str(outside)

def test_two_browse_fragments_on_one_page_do_not_share_an_id(ws, proj):
    "The research modal shows the tree beside the panel's; one id would take both toggles."
    with TestClient(ide_app(ws)) as c:
        ws.memory.clip([proj/'notes.md'])
        other = c.get('/vault/browse', params={'elid': 'researchvault'}).text
        assert 'id="researchvault"' in other and 'id="researchvaulttree"' in other
        assert 'id="vaultbrowse"' not in other
        assert 'id="vaultbrowse"' in c.get('/vault/browse', params={'elid': 'a b#<script>'}).text \
            or 'id="ab' in c.get('/vault/browse', params={'elid': 'a b#<script>'}).text

def test_reindex_reports_what_it_reread(ws, proj):
    with TestClient(ide_app(ws)) as c:
        ws.memory.clip([proj/'notes.md'])
        said = c.post('/vault/reindex').text
        assert 'filed documents' in said and 'id="vaulttidy"' in said

pytest.importorskip('vishalakshi')

def _old_store(path, docs):
    "An old-format leela memory: a litesearch store named `memory`, which is what Memory wrote."
    from vishalakshi import Vault
    v = Vault(path, store='memory', offline=True)
    for title, kind, text in docs:
        v.add(text, title, source=f'{kind}://{title.replace(" ", "-")}', kind=kind,
              meta={'agent': {'revision': 1}})
    return v

def test_documents_come_across_with_their_kind_and_meta(tmp_path):
    _old_store(tmp_path/'web.db', [('Working state', 'agent-state', '# Rules\n\nBe careful.'),
                                   ('core', 'agent-note', 'Text between tool calls is not shown.')])
    got = {d['title']: d for d in read_old(tmp_path/'web.db')}
    assert set(got) == {'Working state', 'core'}
    assert got['Working state']['kind'] == 'agent-state'
    assert got['core']['meta']['agent']['revision'] == 1
    assert 'Be careful' in got['Working state']['text']

def test_a_deleted_document_stays_deleted(tmp_path):
    "WAL-aware backup must not resurrect forgotten documents."
    v = _old_store(tmp_path/'web.db', [('keep', 'agent-note', 'keep this one'),
                                       ('drop', 'agent-note', 'this one was forgotten')])
    doc_id = next(d['id'] for d in v.sources() if d['title'] == 'drop')
    v.forget(doc_id)
    assert (tmp_path/'web.db-wal').exists(), 'precondition: the delete is still in the WAL'
    titles = [d['title'] for d in read_old(tmp_path/'web.db')]
    assert titles == ['keep'], f'a deleted document came back: {titles}'

def test_the_source_file_is_never_written_to(tmp_path):
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

def test_every_shelf_shares_one_encoder(tmp_path):
    "Each `mk_encoder` builds its own ~1GB matrix, so a shelf must never resolve a second one."
    m = Memory(shelf='proj', path=tmp_path/'vault.db', offline=True)
    for shelf in ('proj', GLOBAL, 'rishi', 'cassowary'): m._store(shelf)
    assert len(m._stores) == 4
    assert len({id(v.enc.model) for v in m._stores.values()}) == 1

def test_encoder_is_shared_across_memories_and_vault_files(tmp_path):
    "Two vault files are two `Memory` objects; the weights behind them are still one."
    a = Memory(shelf='one', path=tmp_path/'a.db', offline=True)._store('one')
    b = Memory(shelf='two', path=tmp_path/'b.db', offline=True)._store('two')
    assert a.enc.model is b.enc.model

def test_a_prebuilt_encoder_is_passed_through_untouched(tmp_path):
    "`shared_encoder` caches names; anything already built is the caller's object to keep."
    from leela.blocks.memory.memory import shared_encoder
    built = shared_encoder(None, offline=True)
    assert shared_encoder(built, offline=True) is built
