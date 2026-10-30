import asyncio, json, sys
from types import SimpleNamespace
import pytest
from abhyasa.contract import validate_nb_spec
from leela.blocks.learn import tools
from leela.blocks.learn.tools import make_tool_env, tool_dir, tool_key, tool_kernel, tool_python
from leela.blocks.nb.lesson import ENV_GONE, EnvGone, bind_env, step_lesson
from leela.blocks.nb.nb import Notebook
from leela.blocks.runtime.kernels import python_for
from leela.workspace import Workspace
from learn_data import NB_JID, nb_walk, rig  # noqa: F401
from test_learn_tools import fake, ready_env

@pytest.fixture(autouse=True)
def data_home(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path/'data'))
    monkeypatch.setattr(tools, 'index_env', lambda key: None)

STEP = dict(walk=NB_JID, step=0, section='2 Captions', note='')

def spec(requires=('six',)):
    return validate_nb_spec(dict(task='Write `caption(ep)`.', fname='caption', stub='def caption(ep):\n    ...', requires=list(requires),
                                 tests=[dict(test="assert caption({'desc': 'a'}) == 'a'", say='one episode', shown=True)],
                                 data=[], run=dict(say='Run it.', makes='', minutes=1, predict=''), demo=''))

def lesson(folder, env=None, name='w-0.ipynb'):
    "A walk-step lesson that requires six, saved in `folder`, with an output on its run cell."
    nb = step_lesson('Caption', STEP, spec(), env=env, file=name)
    run = next(c for c in nb.cells if (c.extra.get('lesson') or {}).get('role') == 'run')
    run.execution_count, run.outputs = 1, [{'output_type': 'stream', 'name': 'stdout', 'text': 'learner output\n'}]
    nb.save(p := folder/name)
    return p

def capture(ws):
    "The `python` each kernel start asks the pool for; no kernel starts, and a live one is returned as `KernelPool.get` does."
    seen = []
    async def get(key, **kw):
        if (k := ws.pool.kernels.get(key)) is not None: return k
        seen.append(kw['python'])
        return SimpleNamespace(python=kw['python'], alive=True, busy=False)
    ws.pool.get = get
    return seen

def kernel(ws, p):
    ws.open(p)
    return asyncio.run(ws.kernel(ws.tab))

def test_a_bound_lesson_runs_in_its_environment_and_a_plain_notebook_in_the_project(tmp_path):
    key = ready_env(['six'])
    p, plain = lesson(tmp_path, key), tmp_path/'plain.ipynb'
    Notebook([]).save(plain)
    assert Notebook.load(p).meta['lesson']['env'] == key, 'a lesson made with a ready environment records it'
    for _ in range(2):   # the second Workspace is the lesson reopened
        ws = Workspace(roots=[tmp_path], python=sys.executable)
        try:
            seen = capture(ws)
            kernel(ws, p); kernel(ws, plain)
            assert seen == [str(tool_python(key)), python_for(ws.cwd_for(ws.tab), ws)] and seen[0] != seen[1]
        finally: ws.shutdown_now()

def test_a_lesson_made_before_the_environment_binds_it_when_ready_and_restarts_its_kernel(tmp_path):
    from leela.core.session import DocStore
    p = lesson(tmp_path)
    ws = Workspace(roots=[tmp_path], python=sys.executable)
    ws.docstore = DocStore(ws)
    try:
        seen = capture(ws)
        kernel(ws, p)
        assert seen == [python_for(ws.cwd_for(ws.tab), ws)], 'no environment yet: the project Python'
        closed = []
        async def shutdown(): closed.append(True)
        k = ws.kernel_key(ws.tab)
        ws.pool.kernels[k] = SimpleNamespace(python=seen[0], alive=True, busy=True, shutdown=shutdown)
        key = ready_env(['six'])
        kernel(ws, p)
        assert closed == [] and len(seen) == 1, 'a busy kernel is not taken from its run'
        ws.pool.kernels[k].busy = False
        kernel(ws, p)
        assert closed == [True] and seen[-1] == str(tool_python(key)) and ws.kernel_key(ws.tab).startswith('tab:')
        live = ws.docstore.doc_for(ws.tab)
        assert live.meta['lesson']['env'] == key and live.dirty and 'env' not in Notebook.load(p).meta['lesson'], 'the open copy takes the key; its save writes it'
        assert all(not c.fresh for c in live.cells if c.cell_type == 'code'), 'its outputs came from the old kernel'
    finally: ws.shutdown_now()

def test_binding_an_existing_lesson_changes_only_its_metadata(tmp_path):
    from leela.blocks.fs.fs import Sandbox
    p, key = lesson(tmp_path), ready_env(['six'])
    before = json.loads(p.read_text())
    bind_env(Sandbox([tmp_path]), p, key)
    after = json.loads(p.read_text())
    assert json.dumps(after['cells']) == json.dumps(before['cells']) and after['cells'][-2]['outputs'][0]['text'] == ['learner output\n']
    assert after['metadata']['lesson'] == before['metadata']['lesson'] | {'env': key}
    assert {k: v for k, v in after['metadata'].items() if k != 'lesson'} == {k: v for k, v in before['metadata'].items() if k != 'lesson'}
    live = Notebook.load(p); live.meta['lesson'].pop('env'); was = p.read_bytes()
    bind_env(Sandbox([tmp_path]), p, key, live)
    assert live.meta['lesson']['env'] == key and live.dirty and p.read_bytes() == was, 'an open copy takes the key, and the file waits for its save'

def test_reopening_a_lesson_from_the_step_binds_the_ready_environment_in_its_metadata(rig, monkeypatch, tmp_path_factory):
    c, ws, lr, j, root = rig
    monkeypatch.setenv('HOME', str(tmp_path_factory.mktemp('home')))
    nb_walk(lr, requires=['six'])
    assert c.post('/learn/open', data=dict(walk=NB_JID, step='0')).status_code == 200
    p = root/'lessons'/f'{NB_JID}-0.ipynb'
    head = Notebook.load(p).cells[0].source
    assert 'This lesson needs six. [Set up the environment](</learn?walk=comic-ab12&step=0>)' in head and 'env' not in Notebook.load(p).meta['lesson']
    d = json.loads(p.read_text()); d['cells'][-2]['outputs'] = [{'output_type': 'stream', 'name': 'stdout', 'text': ['mine\n']}]
    p.write_text(json.dumps(d)); before = json.loads(p.read_text())['cells']
    key = ready_env(['six'])
    assert c.post('/learn/open', data=dict(walk=NB_JID, step='0')).status_code == 200
    after = json.loads(p.read_text())
    assert after['metadata']['lesson']['env'] == key and json.dumps(after['cells']) == json.dumps(before)

def test_a_missing_or_broken_environment_says_one_line_and_never_uses_the_project_python(tmp_path):
    key = tool_key(['six'])
    p = lesson(tmp_path, key)
    ws = Workspace(roots=[tmp_path], python=sys.executable)
    try:
        seen = capture(ws)
        with pytest.raises(EnvGone) as e: kernel(ws, p)
        assert str(e.value) == ENV_GONE == 'The environment for this lesson is missing or broken. Open the step and press Set up the environment.'
        ready_env(['six']); (tool_dir(key)/'kernel').unlink()
        assert tool_python(key) and not tool_kernel(key)
        with pytest.raises(EnvGone): kernel(ws, p)
        assert seen == []
    finally: ws.shutdown_now()

def test_a_lesson_whose_exercise_names_unusable_requires_runs_in_the_project_kernel(tmp_path):
    from leela.blocks.nb.exercise import exercise_meta
    ws = Workspace(roots=[tmp_path], python=sys.executable)
    try:
        seen = capture(ws)
        for i, bad in enumerate((['--index-url=x'], 3, [{'six': 1}])):
            p = lesson(tmp_path, name=f'w-{i}.ipynb'); nb = Notebook.load(p)
            next(m for c in nb.cells if (m := exercise_meta(c)))['requires'] = bad
            nb.save(p)
            kernel(ws, p)
            assert seen[-1] == python_for(ws.cwd_for(ws.tab), ws), bad
    finally: ws.shutdown_now()

def test_a_lesson_kernel_that_fails_to_start_offers_the_setup_again(tmp_path):
    from leela.blocks.runtime.kernels import KernelStartError
    p, plain = lesson(tmp_path, ready_env(['six'])), tmp_path/'plain.ipynb'
    Notebook([]).save(plain)
    ws = Workspace(roots=[tmp_path], python=sys.executable)
    try:
        async def get(key, **kw): raise KernelStartError('No module named ipykernel')
        ws.pool.get = get
        with pytest.raises(EnvGone) as e: kernel(ws, p)
        assert str(e.value) == ENV_GONE and isinstance(e.value.__cause__, KernelStartError)
        with pytest.raises(KernelStartError) as e: kernel(ws, plain)
        assert not isinstance(e.value, EnvGone), 'a plain notebook keeps the start error'
    finally: ws.shutdown_now()

def test_the_run_routes_answer_the_one_line(tmp_path):
    from starlette.testclient import TestClient
    from leela.app import ide_app
    p = lesson(tmp_path, tool_key(['six']))
    ws = Workspace(roots=[tmp_path], approvals='auto', python=sys.executable)
    ws.open(p)
    try:
        with TestClient(ide_app(ws)) as c:
            nb = Notebook.load(p); i = next(n for n, x in enumerate(nb.cells) if x.cell_type == 'code')
            for route in ('/nb/run', '/nb/run/stream'):
                r = c.post(route, json=dict(path=str(p), i=i, id=nb.cells[i].id))
                assert r.status_code == 409 and r.json() == dict(ok=False, error=ENV_GONE), route
    finally: ws.shutdown_now()

def test_the_setup_job_installs_the_requirements_with_the_kernel_package():
    run = fake(lambda c: 0)
    r = make_tool_env(['six'], run=run, uv='/u/uv')
    assert r.ok and tool_kernel(r.key) == tool_python(r.key) is not None
    venv, pip = [c for c, _ in run.calls]
    assert venv[:2] == ['/u/uv', 'venv'] and pip[:3] == ['/u/uv', 'pip', 'install'] and 'six' in pip
    assert any(a.startswith('ipykernel') for a in pip) and pip[-len(tools.kernel_reqs()):] == tools.kernel_reqs()
    (tool_dir(r.key)/'kernel').unlink()
    run = fake(lambda c: 0)
    assert make_tool_env(['six'], run=run, uv='/u/uv').ok and [c[1] for c, _ in run.calls] == ['pip'] and tool_kernel(r.key)
    assert (tool_dir(r.key)/'ready').read_text() == 'six\n', 'an environment made before the kernel package keeps its folder and gets only the install'
