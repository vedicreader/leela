"An ipykernel whose shell can stop answering (7.0 to 7.3, ipykernel#1529): the warning on the kernel and runtime UI, the stopped shell on the cell, and the lesson environments."
import json
from types import SimpleNamespace
import pytest
from starlette.testclient import TestClient
from conftest import FakeKernel
from leela.app import ide_app
from leela.blocks.learn import tools
from leela.blocks.runtime.kernels import ExecOutcome
from leela.workspace import Workspace

NOTICE = {'kind': 'ipykernel_stall', 'python': '/p/bin/python', 'version': '7.2.0', 'floor': '7.4',
          'message': 'This environment has ipykernel 7.2, which can stop answering. Upgrade it to 7.4 or later.'}

class Stopped(FakeKernel):
    "A gateway kernel as kunda leaves it once its shell stopped reading: every execute ends at once with `shell_stopped`."
    notice = None
    def __init__(self): self.codes = []
    async def execute(self, code, **kw):
        self.codes.append(code)
        return ExecOutcome(ok=False, lost=True, reason='shell_stopped', error="the kernel's shell stopped answering; restart the kernel to go on")

def _nb(tmp_path):
    p = tmp_path/'s.ipynb'
    p.write_text(json.dumps({'cells': [{'cell_type': 'code', 'id': 'c0', 'source': 'x = 1', 'metadata': {}, 'outputs': [], 'execution_count': None}],
                             'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    return p

def _done(r): return json.loads(next(l for l in r.text.splitlines() if l.startswith('data: ') and '"cell"' in l)[6:])

def test_a_stopped_shell_shows_on_the_cell_with_a_restart_and_no_more_is_sent_to_the_kernel(tmp_path):
    "Before, Leela ran its lost-reply check on the deaf shell, which waited and then blamed a lost reply."
    p, k = _nb(tmp_path), Stopped()
    ws = Workspace(roots=[tmp_path], approvals='auto'); ws.open(p)
    async def runtime(tab=None): return k
    ws.runtime = runtime
    with TestClient(ide_app(ws)) as c:
        body = {'i': 0, 'id': 'c0', 'source': 'x = 1', 'path': str(p)}
        for d in (c.post('/nb/run', json=body).json(), _done(c.post('/nb/run/stream', json=body))):
            assert d['reason'] == 'shell_stopped' and d['lost'] and not d['ok'], d
            assert [o['ename'] for o in d['cell']['outputs']] == ['ShellStopped'] and 'Restart the kernel' in d['cell']['outputs'][0]['evalue']
        replay = c.post('/nb/run/state', json={'path': str(p), 'id': 'c0'}).json()
        assert replay['cell']['outputs'][-1]['ename'] == 'ShellStopped', 'a page that lost the stream sees the same'
    ws.shutdown_now()
    assert k.codes == ['x = 1', 'x = 1'], 'one execute for each run, and no `_settle_lost` execute on the deaf shell'

def test_the_kernel_pill_and_picker_carry_the_kernels_ipykernel_notice(tmp_path):
    k = FakeKernel(); k.notice = NOTICE
    ws = Workspace(roots=[tmp_path])
    ws.runtime_peek = ws.kernel_peek = lambda tab=None: k
    with TestClient(ide_app(ws)) as c: assert c.get('/kernel/info').json()['notice'] == NOTICE
    assert ws.kernel_options()['notice'] == NOTICE
    k.notice = None
    assert ws.kernel_options()['notice'] is None

def test_the_runtime_check_offers_to_upgrade_a_project_ipykernel_that_can_stall(tmp_path):
    "kunda's probe reads the version the project's Python reports; this one reports 7.2."
    py = tmp_path/'.venv'/'bin'/'python'
    py.parent.mkdir(parents=True); py.write_text('#!/bin/sh\necho 7.2.0\n'); py.chmod(0o755)
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as c: info = c.get('/runtime/info').json()
    assert info['needs_upgrade'] and not info['needs_support'] and info['notice']['version'] == '7.2.0', info

def _stale_env(names=('httpx',), version='7.2.0'):
    "A ready lesson tool environment, made before Leela asked for ipykernel 7.4, as uv leaves one on disk."
    key = tools.tool_key(list(names))
    d = tools.tool_dir(key)
    py = d/'.venv'/'bin'/'python'
    py.parent.mkdir(parents=True); py.write_text(''); py.chmod(0o755)
    (d/'.venv'/'pyvenv.cfg').write_text('home = /nowhere\n')
    (d/'.venv'/'lib'/'python3.12'/'site-packages'/f'ipykernel-{version}.dist-info').mkdir(parents=True)
    for f in ('ready', 'kernel', 'indexed'): (d/f).write_text('\n'.join(names) + '\n')
    return key, py

@pytest.fixture
def data_home(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path/'data'))
    monkeypatch.setattr(tools, 'index_env', lambda key: None)

def test_a_lesson_environment_on_a_stalling_ipykernel_gets_its_kernel_packages_again(data_home):
    key, py = _stale_env()
    assert tools.tool_kernel(key) == py and tools.tool_stale(key), 'it still runs the open lesson, and it is stale'
    runs = []
    def run(cmd, **kw):
        runs.append(cmd)
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    r = tools.make_tool_env(['httpx'], run=run, uv='/u/uv')
    assert r.ok and [c[1] for c in runs] == ['pip'] and runs[0][-2:] == tools.kernel_reqs() and 'ipykernel>=7.4' in runs[0]
    fresh, _ = _stale_env(('rich',), version='7.4.1')
    assert not tools.tool_stale(fresh)
    runs.clear()
    assert tools.make_tool_env(['rich'], run=run, uv='/u/uv').ok and runs == [], 'a current one is left alone'

def test_upgrading_the_kernel_of_a_lesson_goes_through_its_tool_environment(data_home, tmp_path, monkeypatch):
    "`install_kernel_support` would add the project packages to a wheels-only lesson environment, so the route asks `make_tool_env`."
    key, py = _stale_env()
    assert tools.tool_of(py) == key and tools.tool_of(tmp_path/'.venv'/'bin'/'python') is None
    made = []
    monkeypatch.setattr(tools, 'make_tool_env', lambda names: made.append(names) or SimpleNamespace(ok=True, python=str(py), error=''))
    import kunda.support
    monkeypatch.setattr(kunda.support, 'install_kernel_support', lambda py: pytest.fail('a lesson environment is not a project'))
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as c: r = c.post('/runtime/support', json={'python': str(py)})
    assert r.status_code == 200 and r.json()['ok'] and made == [['httpx']], r.text
