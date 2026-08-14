"""The vault as something you can read, not only write to: browse, open, search, judge, attach.

Driven through the real app, because the reader tab is a client of these routes and the shapes
it depends on -- every row knowing its shelf, every section knowing its node id -- are the
contract. Offline vaults throughout.
"""

import pytest
from starlette.testclient import TestClient

from leela.app import ide_app
from leela.blocks.memory.memory import Memory
from leela.blocks.memory.vaults import WORKSPACE
from leela.workspace import Workspace


@pytest.fixture
def proj(tmp_path):
    (tmp_path/'notes.md').write_text('# Ranking\n\nDurable notes about recall and ranking.\n' * 3)
    (tmp_path/'minute.md').write_text('# Minute\n\nSigned by Dr Charles Babbage, ada@example.com.\n')
    return tmp_path


@pytest.fixture
def ws(proj, monkeypatch, tmp_path_factory):
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    w = Workspace(roots=[proj])
    w.vaults.file = tmp_path_factory.mktemp('reg')/'vaults.json'   # never the developer's own registry
    return w


def test_a_vault_is_browsable_readable_and_searchable(ws, proj):
    """Browse, open, read a section, search. Each step has to hand the next one what it needs.

    A document row without its shelf, or a section without its node id, is not openable -- the
    reader has nowhere to go next -- so those are asserted rather than the response merely being 200.
    """
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


def test_shelves_can_be_managed_and_an_occupied_one_is_not_dropped(ws, proj):
    with TestClient(ide_app(ws)) as c:
        doc_id = ws.memory.clip([proj/'notes.md'])[0]['doc_id']
        assert c.post('/vault/shelf/move', data={'doc': doc_id, 'target': 'archive'}).json()['moved_to'] == 'archive'
        assert {x['shelf'] for x in c.get('/vault/documents').json()['documents']} == {'archive'}
        assert c.post('/vault/shelf/drop', data={'shelf': 'archive'}).status_code == 400, 'it still holds a document'


def test_an_attached_vault_is_read_only_until_you_say_otherwise(ws, tmp_path):
    """The whole point of attaching a peer tool's vault: leela can read it and cannot write to it.

    Refused at the route, not merely hidden in the UI -- a surface that hides a button while the
    route still writes is not a permission.
    """
    peer = tmp_path/'peer'/'vault.db'
    Memory(shelf='main', path=peer, offline=True)._open()
    with TestClient(ide_app(ws)) as c:
        attached = c.post('/vault/attach', data={'path': str(peer), 'name': 'peer'}).json()
        assert attached['access'] == 'read' and not attached['agent_writable']

        # Every route that writes, not just the one: a guard is only a guard where it is called.
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
    """`agent_writable` has to be enforced where the model calls, not only in the panel.

    Reads stay open on every attached vault -- that is what attaching one is for -- so only the
    writing tools consult it.
    """
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
    """A vault tab names a document, as a pdf tab names a file: the client fetches the contents.

    It has no path, so nothing downstream may treat it as a file on disk -- a tab whose `path`
    were a `vault://` string would reach `fs._check`, git and the linter as a broken one.
    """
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

        # Browsing answers with the tree, unfolded far enough to show something: a vault whose
        # first screen is the single word `files` has answered no question anybody had.
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
        # Only the workspace vault is attached here, and it is the active one, so the row shows
        # the active marker rather than the button that would move activation to it.
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
        # The shelf is the top level and is named for the project, so what must not appear is
        # the path chrome above the documents rather than the project's own name.
        for chrome in ('>private<', '>var<', '>folders<', '>T<'):
            assert chrome not in tree, chrome
        shelf = ws.memory.shelf_name
        # Closed below the shelf: a folder costs one row however much is under it.
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
    # A sibling of the open root, not a child of it: `proj` *is* `tmp_path`, so anything under
    # that is inside the workspace and would prove nothing.
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
        # An id is written into a selector, so it is reduced to what can safely go in one.
        assert 'id="vaultbrowse"' in c.get('/vault/browse', params={'elid': 'a b#<script>'}).text \
            or 'id="ab' in c.get('/vault/browse', params={'elid': 'a b#<script>'}).text


def test_reindex_reports_what_it_reread(ws, proj):
    with TestClient(ide_app(ws)) as c:
        ws.memory.clip([proj/'notes.md'])
        said = c.post('/vault/reindex').text
        assert 'filed documents' in said and 'id="vaulttidy"' in said
