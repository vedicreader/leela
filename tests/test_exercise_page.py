import json, sys
import pytest
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.blocks.nb.exercise import exercise_cells, exercise_meta
from leela.blocks.nb.nb import Cell, Notebook
from leela.workspace import Workspace

SPEC = dict(task='Double a number.', fname='double', stub='def double(x):\n    pass', tests=[
    dict(say='A positive number', test='assert double(2) == 4', shown=True),
    dict(say='A negative number', test='assert double(-123) == -246', shown=False)])
GOOD = 'def double(x):\n    return x * 2'
HIDDEN = ('-123', '-246', 'assert double(-123)')

@pytest.fixture
def rig(tmp_path):
    p = tmp_path/'lesson.ipynb'
    task, code = exercise_cells(SPEC)
    Notebook([Cell(source='print("plain")'), task, code]).save(p)
    ws = Workspace(roots=[tmp_path], approvals='auto', python=sys.executable)
    ws.open(p)
    try:
        with TestClient(ide_app(ws)) as client:
            client.get('/tab/state')
            yield client, p, code, dict(path=str(p), i=2, id=code.id)
    finally: ws.shutdown_now()

def never_hidden(text):
    for hidden in HIDDEN: assert hidden not in text, hidden

def on_disk(p): return Notebook.load(p)[2].extra['exercise']['tests']

def test_no_route_sends_a_hidden_test_to_the_page(rig):
    client, p, code, at = rig
    opened = client.get('/tab/state')
    never_hidden(opened.text)
    tests = opened.json()['cells'][2]['extra']['exercise']['tests']
    assert tests[0] == SPEC['tests'][0] and tests[1] == dict(say='A negative number', shown=False)
    never_hidden(client.get('/tab/disk', params=dict(path=str(p))).text)
    ran = client.post('/nb/run', json=dict(at, source=GOOD))
    assert ran.status_code == 200 and ran.json()['ok'], ran.text
    never_hidden(ran.text)
    streamed = client.post('/nb/run/stream', json=dict(at, source=GOOD))
    assert streamed.status_code == 200 and 'event: done' in streamed.text, streamed.text
    never_hidden(streamed.text)
    state = client.post('/nb/run/state', json=at)
    assert state.json()['cell']['extra']['exercise']['tests'][1] == dict(say='A negative number', shown=False)
    never_hidden(state.text)
    edited = client.post('/nb/edit', json=dict(path=str(p), op='insert', i=0))
    assert edited.status_code == 200 and edited.json()['ok'], edited.text
    never_hidden(edited.text)

def test_the_page_saving_or_editing_never_removes_a_hidden_test(rig):
    client, p, code, at = rig
    page = client.get('/tab/state').json()['cells']
    page[2]['source'] = GOOD
    saved = client.post('/nb/save', json=dict(path=str(p), cells=[dict(c, i=n) for n, c in enumerate(page)]))
    assert saved.json()['ok'], saved.text
    assert Notebook.load(p)[2].source == GOOD and on_disk(p) == SPEC['tests']
    assert client.post('/nb/edit', json=dict(path=str(p), op='source', i=2, id=code.id, source='x = 1')).json()['ok']
    assert client.post('/nb/save', json=dict(path=str(p))).json()['ok']
    assert Notebook.load(p)[2].source == 'x = 1' and on_disk(p) == SPEC['tests']

def test_a_pasted_exercise_never_holds_a_test_it_cannot_run(rig):
    client, p, code, at = rig
    copied = client.get('/tab/state').json()['cells'][2]
    r = client.post('/nb/edit', json=dict(path=str(p), op='paste_many', i=3, cells=[copied]))
    assert r.status_code == 200 and r.json()['ok'], r.text
    never_hidden(r.text)
    foreign = dict(copied, id='from-another-notebook')
    assert client.post('/nb/edit', json=dict(path=str(p), op='paste_many', i=0, cells=[foreign])).json()['ok']
    assert client.post('/nb/save', json=dict(path=str(p))).json()['ok']
    held = [c for c in Notebook.load(p).cells if exercise_meta(c)]
    assert len(held) == 2 and all(m['tests'] == SPEC['tests'] for m in map(exercise_meta, held))
