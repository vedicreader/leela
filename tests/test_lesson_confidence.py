import pytest
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.blocks.nb.lesson import lesson_notebook
from leela.blocks.nb.nb import Notebook
from leela.workspace import Workspace

@pytest.mark.parametrize('confidence', [10, 30, 50, 70, 90, None])
def test_prediction_confidence_uses_cell_edit_and_save(tmp_path, confidence):
    path = tmp_path/'lesson.ipynb'
    nb = lesson_notebook('Confidence')
    nb[2].extra['other'] = {'keep': True}
    nb.save(path)
    ws = Workspace(roots=[tmp_path])
    ws.open(path)
    with TestClient(ide_app(ws)) as client:
        client.get('/tab/state')
        body = dict(op='lesson_confidence', path=str(path), i=2, id=nb[2].id, confidence=confidence)
        r = client.post('/nb/edit', json=body)
        assert r.status_code == 200, r.text
        expected = {**nb[2].extra['lesson']}
        if confidence is not None: expected['confidence'] = confidence
        assert r.json()['cells'][2]['extra'] == {'lesson': expected, 'other': {'keep': True}}
        saved = client.post('/nb/save', json={'path': str(path)})
        assert saved.status_code == 200, saved.text
        assert Notebook.load(path)[2].extra == r.json()['cells'][2]['extra']
        if confidence is not None:
            undone = client.post('/nb/edit', json=dict(op='undo', path=str(path))).json()
            assert undone['cells'][2]['extra'] == nb[2].extra

@pytest.mark.parametrize('confidence', [0, 60, True, '70', 70.0])
def test_prediction_confidence_rejects_invalid_values(tmp_path, confidence):
    path = tmp_path/'lesson.ipynb'
    nb = lesson_notebook('Confidence')
    nb.save(path)
    ws = Workspace(roots=[tmp_path]); ws.open(path)
    with TestClient(ide_app(ws)) as client:
        client.get('/tab/state')
        r = client.post('/nb/edit', json=dict(op='lesson_confidence', i=2, confidence=confidence))
        assert r.status_code == 400 and r.json()['error']
        assert client.get('/tab/state').json()['cells'][2]['extra'] == nb[2].extra

@pytest.mark.parametrize('i', [0, 3, 4])
def test_confidence_changes_only_prediction_markdown(tmp_path, i):
    path = tmp_path/'lesson.ipynb'
    nb = lesson_notebook('Confidence'); nb.save(path)
    ws = Workspace(roots=[tmp_path]); ws.open(path)
    with TestClient(ide_app(ws)) as client:
        client.get('/tab/state')
        r = client.post('/nb/edit', json=dict(op='lesson_confidence', i=i, confidence=70))
        assert r.status_code == 400 and r.json()['error']
