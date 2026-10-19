"Memory: the vault, its shelves, its routes, and the migration into it."

import json
from leela.blocks.memory.memory import GLOBAL, Memory
from leela.blocks.research.research import Doc
import pytest
from leela.blocks.memory.memory import memory_shelf, safe_shelf
from leela.blocks.memory.vaults import WORKSPACE, Vaults
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.workspace import Workspace
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


@pytest.fixture
def mem_vault(tmp_path, monkeypatch):
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    return Memory(shelf='my-repo', path=tmp_path/'vault.db', offline=True)

def _ids(m): return [d.get('doc_id') or d.get('id') for d in m.documents()]

def test_two_threads_opening_one_shelf_open_it_once(tmp_path, monkeypatch):
    "The poll tick and a request both reached `_store` first; each built a Vault over the same file, and the native opens raced to a bus error."
    import threading, time, vishalakshi
    built = []
    class SlowVault:
        def __init__(self, path, **kw): built.append(threading.current_thread().name); time.sleep(0.2)
    monkeypatch.setattr(vishalakshi, 'Vault', SlowVault)
    mem = Memory(shelf='proj', path=tmp_path/'vault.db', offline=True)
    got = {}
    def open_it(who): got[who] = mem._store('proj')
    ts = [threading.Thread(target=open_it, args=(w,), name=w) for w in ('poll', 'request')]
    for t in ts: t.start()
    for t in ts: t.join(5)
    assert len(built) == 1, f'the shelf was opened by {built}'
    assert got['poll'] is got['request']


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


def test_a_workspace_with_no_project_open_lists_each_document_once(mem_vaults, tmp_path):
    "One shelf must not answer under two names."
    m = Memory(shelf='main', path=tmp_path/'noproject.db', offline=True)
    m.clip([tmp_path/'notes.md'])
    assert [d['shelf'] for d in m.all_documents()] == ['main']
    assert [d['shelf'] for d in m.all_documents(shelves=['store'])] == ['main'], 'either name reaches the one shelf'


def test_a_retrieval_policy_masks_or_withholds_what_the_model_would_have_read(mem_vaults, tmp_path):
    """The gate is on the retrieval, not on the model: `off` hands the text over, `redact` masks the identifiers in it, `refuse` hands back a stand-in saying what was held."""
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


pytest.importorskip('vishalakshi')

def _old_store(path, docs):
    "An old-format leela memory: a litesearch store named `memory`, which is what Memory wrote."
    from vishalakshi import Vault
    v = Vault(path, store='memory', offline=True)
    for title, kind, text in docs:
        v.add(text, title, source=f'{kind}://{title.replace(" ", "-")}', kind=kind,
              meta={'agent': {'revision': 1}})
    return v


def test_a_deleted_document_stays_deleted(tmp_path):
    "WAL-aware backup must not resurrect forgotten documents."
    v = _old_store(tmp_path/'web.db', [('keep', 'agent-note', 'keep this one'),
                                       ('drop', 'agent-note', 'this one was forgotten')])
    doc_id = next(d['id'] for d in v.sources() if d['title'] == 'drop')
    v.forget(doc_id)
    assert (tmp_path/'web.db-wal').exists(), 'precondition: the delete is still in the WAL'
    titles = [d['title'] for d in read_old(tmp_path/'web.db')]
    assert titles == ['keep'], f'a deleted document came back: {titles}'


def test_running_twice_moves_nothing_the_second_time(tmp_path):
    _old_store(tmp_path/'web.db', [('one', 'agent-note', 'first'), ('two', 'agent-state', 'second')])
    kw = dict(vault_path=tmp_path/'vault.db', old=tmp_path/'web.db', shelf='leela', offline=True)
    first = migrate(apply=True, **kw)
    assert len(first['moved']) == 2 and not first['skipped']
    again = migrate(apply=True, **kw)
    assert not again['moved'], 'a second run re-filed documents'
    assert len(again['skipped']) == 2


def test_every_shelf_shares_one_encoder(tmp_path):
    "Each `mk_encoder` builds its own ~1GB matrix, so a shelf must never resolve a second one."
    m = Memory(shelf='proj', path=tmp_path/'vault.db', offline=True)
    for shelf in ('proj', GLOBAL, 'rishi', 'cassowary'): m._store(shelf)
    assert len(m._stores) == 4
    assert len({id(v.enc.model) for v in m._stores.values()}) == 1



def test_a_clip_parses_on_a_small_pool_and_a_quit_is_not_swallowed(tmp_path, monkeypatch):
    "litesearch picks a pool per core for any 8-file batch with four PDFs; a launch-time resume forked 14 workers per batch."
    from leela.blocks.memory.memory import index_workers
    from kavacha.window import quitting
    got, mem = [], _mem(tmp_path)
    class Shelf:
        name = 'proj'
        def add_files(self, paths, **kw):
            got.append(kw['n_workers'])
            if quitting.is_set(): raise RuntimeError('pool broken')
            return [dict(doc_id='d')]
    monkeypatch.setattr(mem, '_shelf', lambda shelf=None: Shelf())
    monkeypatch.delenv('LEELA_INDEX_WORKERS', raising=False)
    mem.clip([tmp_path/'a.pdf'])
    assert got[-1] == index_workers() <= 2
    monkeypatch.setenv('LEELA_INDEX_WORKERS', '0'); mem.clip([tmp_path/'a.pdf'])
    assert got[-1] == 0
    monkeypatch.setenv('LEELA_INDEX_WORKERS', 'lots'); assert index_workers() <= 2
    quitting.set()
    try:
        with pytest.raises(RuntimeError): mem.clip([tmp_path/'a.pdf'])
    finally: quitting.clear()
    assert mem.clip([tmp_path/'a.pdf']) == [dict(doc_id='d')]


_BROKEN_USEARCH = '''
import warnings
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter('always')
    from leela.blocks.memory.memory import Memory
    from leela.blocks.research.research import Doc
    mem = Memory(shelf='proj', path=%r, offline=True)
    mem.remember(Doc(title='Notes', url='https://example.com/n', kind='page', text='# Memory\\n\\nRecall accuracy matters for every agent.'))
    hits = mem.search('recall accuracy')
offs = [str(x.message) for x in w if ' is off ' in str(x.message)]
assert hits and len(offs) == 1 and '_nk_capabilities' in offs[0], (hits, offs)
print('ok')
'''

def _litesearch_at_least(v):
    from importlib.metadata import version
    return tuple(map(int, version('litesearch').split('.')[:3])) >= v

# 0.1.48 has the fallback and deadlocks agent code search, so the lock keeps 0.1.46 until the release after it.
@pytest.mark.skipif(not _litesearch_at_least((0, 1, 48)), reason='litesearch before 0.1.48 imports usearch unguarded')
def test_the_vault_files_and_finds_when_usearch_does_not_import(tmp_path):
    "On macOS 14 `import usearch` raises, and litesearch 0.1.46 raised it from `database()`, so no vault opened."
    import os, subprocess, sys
    (fake := tmp_path/'fake'/'usearch').mkdir(parents=True)
    (fake/'__init__.py').write_text("raise ImportError(\"dlopen(compiled.so): symbol not found in flat namespace '_nk_capabilities'\")")
    env = {k: v for k, v in os.environ.items() if k != 'LITESEARCH_USEARCH'}
    env.update(PYTHONPATH=os.pathsep.join([str(fake.parent), os.getcwd()]), LITESEARCH_CACHE=str(tmp_path/'cache'))
    r = subprocess.run([sys.executable, '-c', _BROKEN_USEARCH % str(tmp_path/'vault.db')], capture_output=True, text=True, env=env, timeout=300)
    assert r.stdout.strip().endswith('ok'), r.stdout[-2000:] + r.stderr[-3000:]
