import json
from copy import deepcopy
import pytest
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.blocks.nb.nb import Cell, Notebook, src_hash
from leela.workspace import Workspace
from tests.test_rupaka_inputs import demo


def test_trials_append_only_round_trip_and_undo(demo):
    client, path, body, _ = demo
    assert client.post('/nb/edit', json=dict(op='insert', path=str(path), i=1)).status_code == 200
    trials = []
    for rev, angle in enumerate((30, 60)):
        r = client.post('/nb/edit', json={**body, 'op': 'rupaka_trial', 'rev': rev, 'inputs': {'a': angle, 't': .5}})
        assert r.status_code == 200, r.text
        record = r.json()['record']
        trial = record['trials'][-1]
        assert trial.keys() == {'id', 'n', 'inputs', 'src', 'at'}
        assert trial['n'] == rev + 1 and trial['inputs']['a'] == angle
        assert trial['src'] == body['src'] and trial['id'] and trial['at']
        trials.append(deepcopy(trial))
        assert record['trials'] == trials
    assert len({t['id'] for t in trials}) == 2
    r = client.post('/nb/edit', json={**body, 'rev': 2, 'inputs': {'a': 75}})
    assert r.status_code == 200, r.text
    assert r.json()['record']['trials'] == trials
    for op in ('undo', 'redo'):
        r = client.post('/nb/edit', json=dict(op=op, path=str(path)))
        assert r.status_code == 200, r.text
        assert r.json()['cells'][0]['extra']['rupaka']['throw-angle']['trials'] == trials
    assert client.post('/nb/save', json={'path': str(path)}).status_code == 200
    assert Notebook.load(path)[0].extra['rupaka']['throw-angle']['trials'] == trials


@pytest.mark.parametrize('field,value,status', [('inputs', [], 400), ('inputs', {'range': 35}, 400),
    ('inputs', {'a': 30}, 400), ('rev', True, 400), ('rev', 1, 409), ('src', 'old', 409), ('demo', 'gone', 400)])
def test_trial_validation(demo, field, value, status):
    client, _, body, _ = demo
    r = client.post('/nb/edit', json={**body, 'op': 'rupaka_trial', field: value})
    assert r.status_code == status, r.text
    if status == 409: assert r.json()['kind'] == 'rupaka_conflict' and r.json()['record'] is None


def test_trial_stale_returns_record(demo):
    client, _, body, _ = demo
    first = client.post('/nb/edit', json={**body, 'op': 'rupaka_trial'})
    assert first.status_code == 200, first.text
    stale = client.post('/nb/edit', json={**body, 'op': 'rupaka_trial'})
    assert stale.status_code == 409, stale.text
    assert stale.json()['record'] == first.json()['record']


def test_trial_requires_filed_gates(tmp_path):
    from rupaka.spec import gallery
    from leela.blocks.nb.lesson import fence, lesson_notebook
    spec = gallery()['throw-angle']
    nb = lesson_notebook('Throw'); nb[1].source = fence(spec)
    path = tmp_path/'throw.ipynb'; nb.save(path)
    ws = Workspace(roots=[tmp_path]); ws.open(path)
    with TestClient(ide_app(ws)) as client:
        client.get('/tab/state')
        body = dict(op='rupaka_trial', path=str(path), id=nb[1].id, demo=spec['id'], src=src_hash(nb[1].source), rev=0, inputs=spec['state'])
        r = client.post('/nb/edit', json=body)
        assert r.status_code == 400 and 'gate' in r.json()['error'].lower(), r.text
        pred = dict(path=str(path), cell_id=nb[1].id, src=body['src'], demo=spec['id'], gate='g', picked=60)
        assert client.post('/lesson/predict', json=pred).status_code == 200
        r = client.post('/nb/edit', json=body)
        assert r.status_code == 200, r.text


def test_followup_tool_with_workspace(tmp_path):
    from leela.blocks.agent.ai import _session_tools, WRITE_TOOLS
    from leela.blocks.nb.lesson import fence, lesson_notebook
    from rupaka.spec import gallery
    nb = lesson_notebook('Throw'); nb[1].source = fence(gallery()['throw-angle'])
    path = tmp_path/'follow.ipynb'; nb.save(path)
    ws = Workspace(roots=[tmp_path]); ws.open(path)
    with TestClient(ide_app(ws)) as client:
        client.get('/tab/state')
        tools = {f.__name__: f for f in _session_tools(ws.inline_ai.host)}
        change = tools['set_demo_inputs']
        args = (str(path), nb[1].id, 'throw-angle')
        assert 'set_demo_inputs' in WRITE_TOOLS
        refused = json.loads(change(*args, {'a': 75}, 0))
        assert not refused['ok'] and 'gate' in refused['error'].lower()
        bad = json.loads(change(*args, {'range': 35}, 0))
        assert not bad['ok'] and 'input' in bad['error'].lower()
        pred = dict(path=str(path), cell_id=nb[1].id, src=src_hash(nb[1].source), demo='throw-angle', gate='g', picked=60)
        assert client.post('/lesson/predict', json=pred).status_code == 200
        keep = dict(op='rupaka_trial', path=str(path), id=nb[1].id, demo='throw-angle', src=pred['src'], rev=0, inputs={'a': 60, 't': .5})
        trial = client.post('/nb/edit', json=keep).json()['record']['trials'][0]
        before = client.get('/tab/state').json()['cells']
        result = json.loads(change(*args, {'a': 75}, 1))
        assert result['ok'] and result['record']['inputs'] == {'a': 75, 't': .5}
        assert result['record']['trials'] == [trial]
        after = client.get('/tab/state').json()['cells']
        assert [(c['id'], c['source']) for c in after] == [(c['id'], c['source']) for c in before]
        stale = json.loads(change(*args, {'a': 30}, 1))
        assert stale['status'] == 409 and stale['record'] == result['record']
        added = tools['add_demo'](str(path), gallery()['softmax-temperature'], nb[1].id)
        assert added and len(client.get('/tab/state').json()['cells']) == len(before) + 1


def test_ordinary_demo_keeps_only_after_lockin(tmp_path):
    from rupaka.spec import gallery
    from leela.blocks.nb.lesson import fence
    nb = Notebook([Cell(cell_type='markdown', source=fence(gallery()['throw-angle']))])
    path = tmp_path/'ordinary.ipynb'; nb.save(path)
    ws = Workspace(roots=[tmp_path]); ws.open(path)
    with TestClient(ide_app(ws)) as client:
        client.get('/tab/state')
        body = dict(op='rupaka_trial', path=str(path), id=nb[0].id, demo='throw-angle', src=src_hash(nb[0].source), rev=0, inputs={'a': 30, 't': .5})
        assert client.post('/nb/edit', json=body).status_code == 400
        pred = dict(path=str(path), cell_id=nb[0].id, src=body['src'], demo='throw-angle', gate='g', picked=60)
        r = client.post('/lesson/predict', json=pred)
        assert r.status_code == 200 and r.json()['logged'] is False
        kept = client.post('/nb/edit', json=body)
        assert kept.status_code == 200, kept.text
