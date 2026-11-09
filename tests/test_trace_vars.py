"The run trace: the route, the diff against the last run, the text for the agent, and an old kunda."
import sys
import pytest
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.blocks.modes.modes import cell_anchor
from leela.blocks.nb.nb import Cell, Notebook
from leela.blocks.vars import trace as tr
from leela.workspace import Workspace

BS = """def bsearch(a, x):
    low, high = 0, len(a) - 1
    while low <= high:
        mid = (low + high) // 2
        if a[mid] < x: low = mid + 1
        elif a[mid] > x: high = mid - 1
        else: return mid
    return -1
bsearch([1, 3, 5, 7, 9, 11], %d)"""

@pytest.fixture
def rig(tmp_path):
    p = tmp_path/'t.ipynb'
    nb = Notebook([Cell(source=BS % 7), Cell(source='y = 1')])
    nb.save(p)
    ws = Workspace(roots=[tmp_path], approvals='auto', python=sys.executable)
    ws.open(p)
    try:
        with TestClient(ide_app(ws)) as client:
            client.get('/tab/state')
            tab, live, lock = ws.docstore.owner(str(p))
            yield client, ws, p, live, (lambda src=None: dict(path=str(p), id=live[0].id, **({} if src is None else dict(source=src))))
    finally: ws.shutdown_now()

def rows(m, n): return next(r for r in m['table']['lines'] if r['line'] == n)

def test_a_traced_run_returns_the_cell_and_a_column_per_pass(rig):
    client, ws, p, live, body = rig
    r = client.post('/vars/trace', json=body()).json()
    assert r['ok'] and r['cell']['execution_count'] and any('3' in o.get('data', {}).get('text/plain', '') for o in r['cell']['outputs'])
    m = r['trace']
    assert [x['values'] for x in rows(m, 4)['iterations']] == [{'mid': '2'}, {'mid': '4'}, {'mid': '3'}]
    assert not m['has_prev'] and len(m['states']) == m['table']['steps'] and m['series']['mid']['numeric']

def test_a_second_run_marks_the_values_that_changed_with_the_old_one(rig):
    client, ws, p, live, body = rig
    client.post('/vars/trace', json=body())
    r = client.post('/vars/trace', json=body(BS % 11)).json()
    m = r['trace']
    assert m['has_prev'] and m['table']['diffs'] > 0
    assert any(x.get('was') for row in m['table']['lines'] for x in row['iterations'])
    assert client.get('/vars/trace/last', params=dict(path=str(p), id=live[0].id)).json()['trace']['table']['diffs'] == m['table']['diffs']

def test_the_agent_anchor_has_the_trace_only_after_the_person_traced_that_cell(rig):
    client, ws, p, live, body = rig
    ws.note_cell(live[0].id)
    assert '<trace>' not in cell_anchor(ws)
    client.post('/vars/trace', json=body())
    a = cell_anchor(ws)
    assert '<trace>' in a and 'mid: 2 > 4 > 3' in a and len(a) < 4500
    ws.note_cell(live[1].id)
    assert '<trace>' not in cell_anchor(ws)
    ws.note_cell(live[0].id); live[0].source += '\n# edited'
    assert '<trace>' not in cell_anchor(ws)

def test_an_error_still_gives_the_trace_up_to_it(rig):
    client, ws, p, live, body = rig
    r = client.post('/vars/trace', json=body('x = 5\ny = x / 0')).json()
    assert not r['ok'] and {'x': '5'} in [i['values'] for i in rows(r['trace'], 1)['iterations']]

def test_an_older_kunda_says_so_and_the_cell_does_not_run(rig, monkeypatch):
    client, ws, p, live, body = rig
    monkeypatch.setattr(tr, 'trace_support', lambda k=None: 'needs a newer kunda')
    import leela.blocks.vars.app as va
    monkeypatch.setattr(va, 'trace_support', lambda k=None: 'needs a newer kunda')
    assert client.get('/vars/trace/support').json() == {'ok': False, 'why': 'needs a newer kunda'}
    r = client.post('/vars/trace', json=body())
    assert r.status_code == 409 and 'newer kunda' in r.text and live[0].execution_count is None

def test_support_is_off_when_the_kernel_lacks_run_traced():
    class Old: pass
    assert tr.trace_support(Old()) == 'needs a newer kunda'
    assert tr.trace_support() == ''
