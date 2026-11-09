from starlette.testclient import TestClient

from leela.app import ide_app
from leela.blocks.learn import walk
from leela.workspace import Workspace


def state(revision='one', quote=True):
    step = dict(i=0, name='Addition', statement='Add the two values.', status='open', check=dict(question='What is 1 + 1?', kind='short'))
    if quote: step['quote'] = dict(text='A sum joins values.', url='https://example.com/source', title='Source')
    return dict(status='ok', revision=revision, data=dict(title='Numbers', current=0, steps=[step], gauge=dict(addition=dict(state='new'))))


def test_walk_fragment_renders_sources_states_and_revision():
    page = str(walk.walk_fragment(state(), 'walk-1'))
    assert 'A sum joins values.' in page and 'https://example.com/source' in page
    assert 'name="revision" value="one"' in page
    assert 'Understanding' in page
    ungrounded = str(walk.walk_fragment(state(quote=False), 'walk-1'))
    assert 'Ungrounded: no verbatim source' in ungrounded
    assert 'missing walk' in str(walk.walk_fragment(walk.walk_failure('not_found', 'missing walk', 'walk-1'), 'walk-1'))
    assert 'vault locked' in str(walk.walk_fragment(walk.walk_failure('vault_locked', 'vault locked', 'walk-1'), 'walk-1'))
    assert 'The walk changed; here is the current step' in str(walk.walk_fragment(state(), 'walk-1', notice=walk.walk_failure('stale_state', '', 'walk-1')))


def test_open_learn_walk_dedupes_persists_and_restores(tmp_path):
    path = tmp_path/'workspace.json'
    ws = Workspace()
    first = ws.open_learn_walk('workspace', 'walk-1')
    assert ws.open_learn_walk('workspace', 'walk-1') is first and len(ws.tabs) == 1
    ws.save(path)
    restored = Workspace()
    assert restored.reopen_saved_tabs(path) == 1
    assert restored.tab.kind == 'learn_walk' and restored.tab.ref == first.ref


def test_walk_routes_use_selected_vault_settings_and_current_state(ws, monkeypatch):
    calls = []
    memory = object()
    monkeypatch.setattr(walk, 'walk_memory', lambda ctx, vault: calls.append(('vault', vault)) or memory)
    monkeypatch.setattr(walk, 'learn_settings', lambda session: {'walks.steps': 3})
    monkeypatch.setattr(walk, 'walk_state_for', lambda memory, jid, settings: calls.append(('state', memory, jid, settings)) or state('two'))
    def answer(memory, ask, jid, i, answer, attempt_id, settings, revision):
        calls.append(('answer', memory, jid, i, answer, attempt_id, settings, revision))
        return walk.walk_failure('stale_state', 'stale', jid)
    monkeypatch.setattr(walk, 'answer_for', answer)
    with TestClient(ide_app(ws)) as client:
        got = client.get('/learn/walk/walk-1', params={'vault': 'chosen'})
        assert got.status_code == 200 and 'Source' in got.text
        posted = client.post('/learn/walk/walk-1/0/answer', params={'vault': 'chosen'}, data={'answer': '2', 'attempt_id': 'a1', 'revision': 'one'})
    assert 'The walk changed; here is the current step' in posted.text
    assert ('vault', 'chosen') in calls
    assert ('state', memory, 'walk-1', {'walks.steps': 3}) in calls
    assert ('answer', memory, 'walk-1', 0, '2', 'a1', {'walks.steps': 3}, 'one') in calls


def test_walk_open_route_dedupes_tab(ws, monkeypatch):
    memory = object()
    monkeypatch.setattr(walk, 'walk_memory', lambda ctx, vault: memory)
    monkeypatch.setattr(walk, 'learn_settings', lambda session: {})
    monkeypatch.setattr(walk, 'walk_state_for', lambda memory, jid, settings: state())
    with TestClient(ide_app(ws)) as client:
        assert client.post('/learn/walk/open', data={'vault': 'workspace', 'walk': 'walk-1'}).status_code == 200
        assert client.post('/learn/walk/open', data={'vault': 'workspace', 'walk': 'walk-1'}).status_code == 200
    assert len([t for t in ws.tabs if t.kind == 'learn_walk']) == 1
