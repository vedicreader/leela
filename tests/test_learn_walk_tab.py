import json
from starlette.testclient import TestClient

from leela.app import ide_app
from leela.workspace import Workspace, walk_path


def test_a_walk_opens_in_the_one_learn_tab_and_a_second_walk_moves_it(tmp_path):
    ws = Workspace()
    first = ws.open_walk('workspace', 'walk-1')
    assert first.kind == 'learn' and first.page == '/w/walk-1/0' and walk_path('a b') == '/w/a%20b/0' and walk_path('w', None) == '/w/w'
    assert ws.open_walk('workspace', 'walk-2', 3) is first and first.page == '/w/walk-2/3' and len(ws.tabs) == 1
    assert not hasattr(ws, 'open_learn_walk')


def test_a_saved_walk_tab_restores_as_the_learn_tab_at_its_walk(tmp_path):
    path = tmp_path/'workspace.json'
    ws = Workspace(); ws.open_walk('workspace', 'walk-1'); ws.save(path)
    d = json.loads(path.read_text())
    old = dict(d['tabs'][0], kind='learn_walk', ref=json.dumps(['workspace', 'walk-1']), page=''); old.pop('page')
    d['tabs'] = [old]; d['active'] = 0
    path.write_text(json.dumps(d))
    restored = Workspace()
    assert restored.reopen_saved_tabs(path) == 1
    assert [(t.kind, t.page) for t in restored.tabs] == [('learn', '/w/walk-1')] and restored.tab is restored.tabs[0]
    d['tabs'] = [dict(old, page='/w/walk-1/2')]
    path.write_text(json.dumps(d))
    again = Workspace(); again.reopen_saved_tabs(path)
    assert again.tab.page == '/w/walk-1/2'


def test_the_learn_tab_open_route_takes_a_walk_page(ws):
    with TestClient(ide_app(ws)) as client:
        assert client.post('/learn/tab/open', params={'path': '/w/walk-1/0', 'vault': 'workspace'}).status_code == 200
        assert client.post('/learn/tab/open', params={'path': '/w/walk-1/2'}).status_code == 200
    assert [(t.kind, t.page) for t in ws.tabs] == [('learn', '/w/walk-1/2')]
