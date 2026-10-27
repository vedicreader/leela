import asyncio, json, sys, time
import pytest
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.blocks.agent.ai import WRITE_TOOLS, _session_tools
from leela.blocks.nb import exercise
from leela.blocks.nb.exercise import exercise_cells
from leela.blocks.nb.nb import Cell, Notebook
from leela.workspace import Workspace

SPEC = dict(task='Double a number.', fname='double', stub='def double(x):\n    pass', tests=[
    dict(say='A positive number', test='assert double(2) == 4', shown=True),
    dict(say='A negative number', test='assert double(-123) == -246', shown=False)])
GOOD = 'def double(x):\n    return x * 2'
WRONG = 'def double(x):\n    return 999777'
ENDLESS = 'def double(x):\n    while True: pass'

@pytest.fixture
def rig(tmp_path):
    p = tmp_path/'lesson.ipynb'
    task, code = exercise_cells(SPEC)
    nb = Notebook([Cell(source='print("plain")'), task, code])
    nb.save(p)
    ws = Workspace(roots=[tmp_path], approvals='auto', python=sys.executable)
    ws.open(p)
    try:
        with TestClient(ide_app(ws)) as client:
            client.get('/tab/state')
            tab, live, lock = ws.docstore.owner(str(p))
            body = lambda source=code.source, **kw: dict(path=str(p), i=2, id=code.id, source=source, **kw)
            yield client, ws, p, live, lock, code, body
    finally: ws.shutdown_now()

def check(client, body): return client.post('/exercise/check', json=body)

def test_route_pass_fail_and_never_a_hidden_test(rig):
    client, ws, p, live, lock, code, body = rig
    r = check(client, body(GOOD))
    assert r.status_code == 200, r.text
    got = r.json()
    assert got['passed'] == 2 and got['total'] == 2 and [c['status'] for c in got['checks']] == ['pass', 'pass']
    assert [c['say'] for c in got['checks']] == ['A positive number', 'A negative number']
    r = check(client, body(WRONG))
    assert r.status_code == 200, r.text
    got = r.json()
    assert [c['status'] for c in got['checks']] == ['fail', 'fail'] and got['passed'] == 0
    assert got['checks'][0]['got'] == '999777' and 'got' not in got['checks'][1]
    for hidden in ('-246', '-123', 'assert double(-123)', 'expected'): assert hidden not in r.text
    assert got['summary'] == '0 of 2 checks pass.'

def test_route_raised_missing_and_error(rig):
    client, ws, p, live, lock, code, body = rig
    got = check(client, body('x = 1')).json()
    assert got['state'] == 'missing' and got['checks'] == []
    got = check(client, body('1 / 0')).json()
    assert got['state'] == 'raised' and got['checks'] == []
    got = check(client, body('def double(x):\n    raise ValueError("nope")')).json()
    assert [c['status'] for c in got['checks']] == ['error', 'error'] and 'nope' not in json.dumps(got)

def test_route_refuses_before_running_anything(rig):
    client, ws, p, live, lock, code, body = rig
    ran = lambda: [c.execution_count for c in live.cells]
    assert ran() == [None] * 3
    r = check(client, dict(body(GOOD), i=0, id=live[0].id))
    assert r.status_code == 400 and 'not an exercise' in r.text
    r = check(client, dict(body(GOOD), i=1, id=live[1].id))
    assert r.status_code == 400 and 'not an exercise' in r.text
    assert check(client, dict(body(GOOD), i=0)).status_code == 409
    assert check(client, dict(body(GOOD), id='nosuchid')).status_code == 409
    assert check(client, body(GOOD, seq=100)).status_code == 200
    count = ran()
    r = check(client, body(WRONG, seq=50))
    assert r.status_code == 409 and 'out of date' in r.text
    assert ran() == count and live[2].source == GOOD
    client.portal.call(lock.acquire)
    try:
        r = check(client, body(GOOD, seq=200))
        assert r.status_code == 409 and 'in progress' in r.text
        assert ran() == count
    finally: lock.release()
    assert check(client, body(GOOD, seq=300)).status_code == 200

def test_an_endless_learner_function_times_out_within_the_budget(rig, monkeypatch):
    client, ws, p, live, lock, code, body = rig
    assert client.post('/nb/run', json=dict(path=str(p), i=0, id=live[0].id)).status_code == 200
    monkeypatch.setattr(exercise, 'BUDGET', 3)
    started = time.monotonic()
    r = check(client, body(ENDLESS))
    assert time.monotonic() - started < 3 + 3
    assert r.status_code == 200, r.text
    assert [c['status'] for c in r.json()['checks']] == ['timeout', 'timeout']

@pytest.fixture
def tool(rig):
    client, ws, p, live, lock, code, body = rig
    tools = {f.__name__: f for f in _session_tools(ws.inline_ai.host)}
    assert 'check_exercise' in tools and 'check_exercise' not in WRITE_TOOLS
    return tools['check_exercise']

def test_the_agent_gets_the_source_and_every_check(rig, tool):
    client, ws, p, live, lock, code, body = rig
    live[2].source = WRONG
    got = json.loads(tool(str(p), code.id))
    assert got['source'] == WRONG and got['passed'] == 0 and got['total'] == 2
    assert [c['test'] for c in got['checks']] == [t['test'] for t in SPEC['tests']]
    assert [c['status'] for c in got['checks']] == ['fail', 'fail']
    assert [c['got'] for c in got['checks']] == ['999777', '999777']
    assert got['summary'] == '0 of 2 checks pass.'
    assert live[2].execution_count is not None

def test_the_agent_tool_refuses_without_running(rig, tool):
    client, ws, p, live, lock, code, body = rig
    for cid in (live[0].id, live[1].id, 'nosuchid'):
        assert 'not an exercise' in tool(str(p), cid) or 'no cell' in tool(str(p), cid)
    client.portal.call(lock.acquire)
    try: out = tool(str(p), code.id)
    finally: lock.release()
    assert 'in progress' in out
    assert [c.execution_count for c in live.cells] == [None] * 3
