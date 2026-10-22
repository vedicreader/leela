"The direct debugger's routes, now that they are the debug block's rather than `ide_app`'s."

from __future__ import annotations
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.workspace import Workspace


def test_capabilities_resolves_the_interpreter_from_the_project_not_the_first_root(tmp_path):
    "A debugger that lands in another repo's venv reports that repo's debugpy, not this one's."
    from leela.blocks.runtime.kernels import python_for
    a, b = tmp_path/'a', tmp_path/'b'
    for d in (a, b): d.mkdir()
    ws = Workspace(roots=[a, b])
    with TestClient(ide_app(ws)) as client:
        got = client.get('/debug/capabilities').json()
    assert got['python'] == str(python_for(ws.cwd_for(), ws) or got['python'])


def test_a_frame_outside_the_sandbox_is_not_offered_as_openable(tmp_path):
    "`open_path` is the guard that kept a traceback from handing out paths the workspace refuses."
    from leela.blocks.debug.app import state_ui
    (tmp_path/'in.py').write_text('x = 1\n')
    fs = Workspace(roots=[tmp_path]).fs
    state = state_ui(fs, {'frames': [{'source': {'path': str(tmp_path/'in.py')}},
                                     {'source': {'path': '/etc/passwd'}}]})
    assert state['frames'][0]['open_path'] == str(tmp_path/'in.py')
    assert state['frames'][1]['open_path'] == '', 'a path the sandbox refuses is not offered'

