"The direct debugger's routes, now that they are the debug block's rather than `ide_app`'s."

from __future__ import annotations
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.workspace import Workspace

NEEDS_SESSION = ('/debug/state', '/debug/variables?reference=1')
NEEDS_SESSION_POST = ('/debug/evaluate', '/debug/control', '/debug/breakpoints')

def test_capabilities_resolves_the_interpreter_from_the_project_not_the_first_root(tmp_path):
    "A debugger that lands in another repo's venv reports that repo's debugpy, not this one's."
    from leela.blocks.runtime.kernels import python_for
    a, b = tmp_path/'a', tmp_path/'b'
    for d in (a, b): d.mkdir()
    ws = Workspace(roots=[a, b])
    with TestClient(ide_app(ws)) as client:
        got = client.get('/debug/capabilities').json()
    assert got['python'] == str(python_for(ws.cwd_for(), ws) or got['python'])
    assert set(got) == {'python', 'debugpy', 'notebook', 'direct'}

def test_a_relative_program_is_resolved_against_the_checkout_being_worked_in(monkeypatch, tmp_path):
    "Beside the clones is nowhere: `main.py` means the one in the repo the open file is in."
    import subprocess
    from leela.blocks.debug import debug as debug_mod
    orgs = tmp_path/'orgs'; a = orgs/'repo-a'; a.mkdir(parents=True)
    subprocess.run(['git', 'init', '-q', str(a)], check=True)
    (a/'main.py').write_text('print(1)\n')
    launched = {}
    class FakeSession:
        alive = False
        def __init__(self, python, cwd): launched.update(python=str(python), cwd=str(cwd))
        def start_adapter(self): pass
        def launch(self, config, breakpoints): launched['config'] = config
        def disconnect(self): pass
    monkeypatch.setattr(debug_mod, 'DebugSession', FakeSession)
    ws = Workspace(roots=[orgs])
    ws.open(a/'main.py')
    with TestClient(ide_app(ws)) as client:
        assert client.post('/debug/start', json={'program': 'main.py'}).json()['ok']
    assert launched['config']['program'] == str(a/'main.py'), 'the checkout, not the folder of clones'
    assert launched['cwd'] == str(a)

def test_every_debug_route_refuses_the_same_way_with_no_session(tmp_path):
    "One recovery message from every route, so a dead debugger never looks like a dead UI."
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as client:
        for path in NEEDS_SESSION:
            r = client.get(path)
            assert r.status_code == 400 and r.json() == {'ok': False, 'error': 'no direct debugger is active'}, path
        for path in NEEDS_SESSION_POST:
            r = client.post(path, json={})
            assert r.status_code == 400 and r.json() == {'ok': False, 'error': 'no direct debugger is active'}, path

def test_stop_is_idempotent_and_start_says_what_it_needs(tmp_path):
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as client:
        assert client.post('/debug/stop', json={}).json() == {'ok': True}
        r = client.post('/debug/start', json={})
        assert r.status_code == 400 and 'program/module' in r.json()['error']

def test_the_block_declares_the_capabilities_it_uses():
    from leela.blocks import debug as block
    assert set(block.CAPS) == {'fs', 'tab', 'runs', 'debug'}

def test_a_frame_outside_the_sandbox_is_not_offered_as_openable(tmp_path):
    "`open_path` is the guard that kept a traceback from handing out paths the workspace refuses."
    from leela.blocks.debug.app import state_ui
    (tmp_path/'in.py').write_text('x = 1\n')
    fs = Workspace(roots=[tmp_path]).fs
    state = state_ui(fs, {'frames': [{'source': {'path': str(tmp_path/'in.py')}},
                                     {'source': {'path': '/etc/passwd'}}]})
    assert state['frames'][0]['open_path'] == str(tmp_path/'in.py')
    assert state['frames'][1]['open_path'] == '', 'a path the sandbox refuses is not offered'

def test_the_direct_and_notebook_debuggers_share_one_state_object(tmp_path):
    "`ide_app` kept two dicts for this; `DebugState` is the thing `core` already had for it."
    from leela.core import DebugState
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        assert client.post('/debug/stop', json={}).json() == {'ok': True}
    d = DebugState()
    d.direct_session, d.direct_name = object(), 'x'
    d.clear_direct()
    assert d.direct_session is None and d.direct_name == '' and not d.paused
