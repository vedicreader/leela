import asyncio, json, shutil, subprocess, sys, threading, time
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastcore.basics import AttrDict
from leela.blocks.learn import tools
from leela.blocks.learn.tools import (LIBRARY_TOTAL, NO_UV, TOO_LONG, install_cmds, library_check, make_tool_env, tool_dir, tool_job,
                                      tool_key, tool_names, tool_python)
from leela.blocks.nb import exercise
from leela.blocks.nb.exercise import JUDGE, Refused, check_cell, exercise_cells, grade_cell, validate_exercise_spec
from leela.blocks.nb.nb import Cell, Notebook
from learn_data import rig  # noqa: F401

@pytest.fixture(autouse=True)
def data_home(tmp_path, monkeypatch): monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path/'data'))

@pytest.mark.parametrize('bad', [[], list('abcdef'), ['-e .'], ['--index-url=https://x'], ['https://x/p.whl'],
                                 ['../p'], ['/tmp/p'], ['p; rm -rf ~'], ['p @ file:///x'], ['git+https://x'], 'httpx', None, [5]])
def test_tool_names_refuse_options_urls_and_paths(bad):
    with pytest.raises(ValueError): tool_names(bad)

def test_names_key_and_commands():
    assert tool_names(['pydantic-ai-slim[openai]==1.0.2', 'httpx']) == ['httpx', 'pydantic-ai-slim[openai]==1.0.2']
    assert tool_key(['b', 'a'], (3, 13)) == tool_key(['a', 'b'], (3, 13)) != tool_key(['a', 'b'], (3, 12))
    d = tool_dir(tool_key(['httpx'], (3, 13)))
    assert install_cmds(['httpx'], d, '/u/uv', (3, 13)) == [
        ['/u/uv', 'venv', str(d/'.venv'), '--python', '3.13'],
        ['/u/uv', 'pip', 'install', '--python', str(d/'.venv'/'bin'/'python'), '--only-binary', ':all:', 'httpx']]

@pytest.mark.parametrize('key', ['../x', '0123456789ABCDEF', '0123', '', None])
def test_a_bad_key_is_not_a_folder(key):
    with pytest.raises(ValueError): tool_dir(key)
    assert tool_python(key) is None

def fake(code_for, python=True, on=None):
    calls = []
    def run(cmd, **kw):
        calls.append((cmd, kw))
        if on: on(cmd, kw)
        if cmd[1] == 'venv' and python:
            p = Path(cmd[2])/'bin'/'python'
            p.parent.mkdir(parents=True, exist_ok=True); p.write_text(''); p.chmod(0o755)
        return SimpleNamespace(returncode=code_for(cmd), stdout='', stderr='error: no wheel for sdist-only (no source builds allowed)')
    run.calls = calls
    return run

def test_ready_only_after_a_full_install():
    run = fake(lambda c: 0)
    r = make_tool_env(['httpx'], run=run, uv='/u/uv')
    assert r.ok and tool_python(r.key) is not None and (tool_dir(r.key)/'ready').exists()
    assert all(isinstance(a, str) for c, _ in run.calls for a in c)                           # argv lists, no shell
    assert all(kw['stdin'] is subprocess.DEVNULL and kw['capture_output'] for _, kw in run.calls)
    run = fake(lambda c: 1 if c[1] == 'pip' else 0)
    r = make_tool_env(['sdist-only'], run=run, uv='/u/uv')
    assert not r.ok and r.error == 'sdist-only has no wheel for this computer, so Leela cannot install it.' and tool_python(r.key) is None
    assert not (tool_dir(r.key)/'ready').exists()
    run = fake(lambda c: 0)
    assert make_tool_env(['sdist-only'], run=run, uv='/u/uv').ok                              # a half-made folder is made again
    assert make_tool_env(['sdist-only'], run=fake(lambda c: 1), uv='/u/uv').ok                # a ready one is not

def test_other_uv_errors_give_the_last_line():
    run = fake(lambda c: 2)
    run_err = lambda cmd, **kw: SimpleNamespace(**{**vars(run(cmd, **kw)), 'stderr': 'Resolved 3 packages\nerror: Failed to fetch: `https://pypi.org/simple/httpx/`\n'})
    r = make_tool_env(['httpx'], run=run_err, uv='/u/uv')
    assert not r.ok and r.error == 'error: Failed to fetch: `https://pypi.org/simple/httpx/`'

def test_ready_with_no_python_is_not_ready():
    key = tool_key(['httpx'])
    d = tool_dir(key); d.mkdir(parents=True); (d/'ready').write_text('httpx')
    assert tool_python(key) is None
    (d/'stale').write_text('x')
    run = fake(lambda c: 0)
    assert make_tool_env(['httpx'], run=run, uv='/u/uv').ok and len(run.calls) == 2 and not (d/'stale').exists()
    p = d/'.venv'/'bin'/'python'
    p.chmod(0o644)
    assert tool_python(key) is None

def test_no_python_after_the_install_leaves_no_ready():
    r = make_tool_env(['httpx'], run=fake(lambda c: 0, python=False), uv='/u/uv')
    assert not r.ok and r.error and not (tool_dir(r.key)/'ready').exists() and tool_python(r.key) is None

@pytest.mark.parametrize('step', ['venv', 'pip'])
def test_a_step_that_takes_too_long(step):
    def on(cmd, kw):
        if cmd[1] == step: raise subprocess.TimeoutExpired(cmd, kw['timeout'])
    run = fake(lambda c: 0, on=on)
    r = make_tool_env(['httpx'], run=run, uv='/u/uv')
    assert not r.ok and r.error == TOO_LONG and not (tool_dir(r.key)/'ready').exists()
    assert [c[1] for c, _ in run.calls] == (['venv'] if step == 'venv' else ['venv', 'pip'])

def test_both_steps_share_one_budget(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(tools, 'monotonic', lambda: now[0])
    def on(cmd, kw):
        if cmd[1] == 'venv': now[0] += 590
    run = fake(lambda c: 0, on=on)
    assert make_tool_env(['httpx'], run=run, uv='/u/uv', budget=600).ok
    assert [kw['timeout'] for _, kw in run.calls] == [600, 10]
    def slow(cmd, kw):
        if cmd[1] == 'venv': now[0] += 700
    run = fake(lambda c: 0, on=slow)
    r = make_tool_env(['six'], run=run, uv='/u/uv', budget=600)
    assert not r.ok and r.error == TOO_LONG and [c[1] for c, _ in run.calls] == ['venv']

def test_no_uv(monkeypatch):
    monkeypatch.setattr(tools.shutil, 'which', lambda name: None)
    run = fake(lambda c: 0)
    r = make_tool_env(['httpx'], run=run)
    assert not r.ok and r.error == NO_UV == 'Leela needs uv to install packages for a lesson.' and run.calls == []

def test_a_second_install_waits_and_finds_it_ready():
    from leela.workspace import _session_lock
    key = tool_key(['httpx'])
    d, run, out = tool_dir(key), fake(lambda c: 0), []
    with _session_lock(d, timeout=1) as held:
        assert held and d.with_suffix('.lock').exists() and not d.exists()
        t = threading.Thread(target=lambda: out.append(make_tool_env(['httpx'], run=run, uv='/u/uv')))
        t.start(); time.sleep(.3)
        assert t.is_alive() and run.calls == []
        p = d/'.venv'/'bin'/'python'                                                         # the other process finishes
        p.parent.mkdir(parents=True); p.write_text(''); p.chmod(0o755); (d/'ready').write_text('httpx')
    t.join(5)
    assert out and out[0].ok and run.calls == []

def test_the_job_indexes_and_keeps_an_index_failure(monkeypatch):
    seen = []
    monkeypatch.setattr(tools, 'make_tool_env', lambda names: make_tool_env(names, run=fake(lambda c: 0), uv='/u/uv'))
    monkeypatch.setattr(tools, 'index_env', lambda key: seen.append(key))
    job, report = SimpleNamespace(params=dict(names=['httpx'])), lambda **kw: None
    r = tool_job(job, report)
    assert r['ok'] and seen == [r['key']] and 'index_error' not in r
    def boom(key): raise RuntimeError('database is locked')
    monkeypatch.setattr(tools, 'index_env', boom)
    r = tool_job(job, report)
    assert r['ok'] and 'database is locked' in r['index_error'] and tool_python(r['key']) is not None
    monkeypatch.setattr(tools, 'make_tool_env', lambda names: make_tool_env(names, run=fake(lambda c: 1), uv='/u/uv'))
    from leela.blocks.vault.jobs import JobError
    with pytest.raises(JobError, match='has no wheel'): tool_job(SimpleNamespace(params=dict(names=['sdist-only'])), report)

def test_the_workspace_registers_the_job_kind(rig):
    assert 'tool_env' in rig[1].jobs._handlers

def wait(ws, jid, timeout=10):
    end = time.time() + timeout
    while ws.jobs.get(jid).active and time.time() < end: time.sleep(.05)
    return ws.jobs.get(jid)

def test_routes_start_one_job_for_a_key_and_then_say_ready(rig, monkeypatch):
    c, ws = rig[:2]
    go, real = threading.Event(), make_tool_env
    def slow(names):
        go.wait(10)
        return real(names, run=fake(lambda c: 0), uv='/u/uv')
    monkeypatch.setattr(tools, 'make_tool_env', slow)
    monkeypatch.setattr(tools, 'index_env', lambda key: None)
    monkeypatch.setattr(tools.shutil, 'which', lambda name: '/u/uv')
    key = tool_key(['httpx'])
    assert c.get(f'/learn/tool?key={key}').json() == dict(ok=True, ready=False, python=None)
    a = c.post('/learn/tool', json=dict(names=['httpx'])).json()
    b = c.post('/learn/tool', json=dict(names=['httpx'])).json()
    assert a['ok'] and a['key'] == key and a['job']['id'] == b['job']['id'] and a['job']['target'] == key
    assert [j.id for j in ws.jobs.all(kind='tool_env')] == [a['job']['id']]
    go.set()
    assert wait(ws, a['job']['id']).status == 'complete'
    assert c.post('/learn/tool', json=dict(names=['httpx'])).json() == dict(ok=True, key=key, ready=True)
    assert c.get(f'/learn/tool?key={key}').json() == dict(ok=True, ready=True, python=str(tool_dir(key)/'.venv'/'bin'/'python'))
    assert len(ws.jobs.all(kind='tool_env')) == 1

@pytest.mark.parametrize('body', [dict(names=['--index-url=https://x']), dict(names=[]), dict(names='httpx'), dict(), dict(names=None)])
def test_post_refuses_bad_names(rig, body):
    c, ws = rig[:2]
    r = c.post('/learn/tool', json=body)
    assert r.status_code == 400 and r.json()['ok'] is False and 'Traceback' not in r.text and ws.jobs.all(kind='tool_env') == []

def test_get_refuses_a_bad_key(rig):
    r = rig[0].get('/learn/tool?key=../x')
    assert r.status_code == 400 and r.json()['ok'] is False

def test_post_with_no_uv(rig, monkeypatch):
    c, ws = rig[:2]
    monkeypatch.setattr(tools.shutil, 'which', lambda name: None)
    r = c.post('/learn/tool', json=dict(names=['httpx']))
    assert r.status_code == 503 and r.json() == dict(ok=False, error=NO_UV) and ws.jobs.all(kind='tool_env') == []

def test_tool_methods(rig):
    c = rig[0]
    assert c.put('/learn/tool', json={}).status_code == 405

def test_lookup_searches_a_ready_tool_environment(rig, monkeypatch):
    import kosha
    from leela.blocks.learn.app import kosha_for
    c, ws = rig[:2]
    made = []
    class K:
        def __init__(self, dir=None): made.append(dir)
    monkeypatch.setattr(kosha, 'Kosha', K)
    monkeypatch.setattr(ws.search, '_kosha', lambda path=None: 'project')
    make_tool_env(['httpx'], run=fake(lambda c: 0), uv='/u/uv')
    key = tool_key(['httpx'])
    assert isinstance(kosha_for(ws.search, key), K) and made == [tool_dir(key)]
    assert kosha_for(ws.search, tool_key(['six'])) == 'project' and kosha_for(ws.search, '../x') == 'project' and kosha_for(ws.search) == 'project'

SPEC = dict(task='Double a number.', fname='double', stub='def double(x):\n    pass', tests=[
    dict(say='A positive number', test='assert double(2) == 4', shown=True),
    dict(say='A negative number', test='assert double(-123) == -246', shown=False)])
GOOD, WRONG = 'def double(x):\n    return x * 2', 'def double(x):\n    return 999777'
SECRET = 'def double(x):\n    # SECRET_REFERENCE_SOLUTION_7f9c\n    return x*2'

def ready_env(names=('six',)):
    "A ready tool environment for `names` whose Python is this one, so a check needs no install."
    key = tool_key(list(names))
    d = tool_dir(key); p = d/'.venv'/'bin'/'python'
    p.parent.mkdir(parents=True); p.symlink_to(sys.executable); (d/'ready').write_text('\n'.join(names) + '\n')
    return key

def no_install(*a, **kw): pytest.fail('a check must never install')

def test_library_check_needs_a_ready_environment(monkeypatch):
    assert LIBRARY_TOTAL == 20.
    monkeypatch.setattr(tools, 'make_tool_env', no_install)
    key = tool_key(['six'])
    for k in ('nokey', key):
        with pytest.raises(ValueError, match='not ready'): library_check(SPEC, GOOD, k)
    ready_env(); (tool_dir(key)/'.venv'/'bin'/'python').unlink()
    with pytest.raises(ValueError, match='not ready'): library_check(SPEC, GOOD, key)

def test_library_check_runs_the_tool_python_closed_with_hidden_rows(monkeypatch, abhyasa_cfg):
    import abhyasa.check
    key, seen, real = ready_env(), [], abhyasa.check.run_isolated
    monkeypatch.setattr(abhyasa.check, 'run_isolated', lambda *a, **kw: seen.append((a, kw)) or real(*a, **kw))
    r = library_check(SPEC, GOOD, key)
    [(a, kw)] = seen
    assert a[:3] == ('assert', 'double', GOOD) and kw == dict(total=LIBRARY_TOTAL, sandbox=True, python=str(tool_python(key)), unix=True)
    assert [(t['test'], t['hidden']) for t in a[3]] == [(t['test'], not t['shown']) for t in SPEC['tests']]
    assert r['found'] and [(c['status'], c['hidden']) for c in r['checks']] == [('pass', False), ('pass', True)]
    assert r['checks'][1]['got'] is None                                                      # a hidden pass shows no value
    missing = library_check(SPEC, 'x = 1', key)
    assert missing['found'] is False and missing['checks'] == []
    assert [c['status'] for c in library_check(dict(fname='double', tests=['assert double(2) == 4']), GOOD, key)['checks']] == ['pass']

def test_env_round_trips_through_the_spec_and_the_cell(tmp_path):
    key = tool_key(['six'])
    spec = validate_exercise_spec(SPEC | dict(env=key))
    assert spec['env'] == key and validate_exercise_spec(spec) == spec and 'env' not in validate_exercise_spec(SPEC)
    task, code = exercise_cells(SPEC | dict(env=key))
    assert code.extra['exercise']['env'] == key and 'env' not in exercise_cells(SPEC)[1].extra['exercise']
    Notebook([task, code]).save(tmp_path/'l.ipynb')
    assert Notebook.load(tmp_path/'l.ipynb').cells[1].extra['exercise']['env'] == key
    for bad in ('../x', '0123456789ABCDEF', '', 5, ['ab']):
        with pytest.raises(ValueError, match='env'): validate_exercise_spec(SPEC | dict(env=bad))

def no_kernel(): pytest.fail('a check with `env` must not use the live kernel')

def library_cell(key, source):
    task, code = exercise_cells(SPEC | dict(env=key))
    code.source = source
    return Notebook([task, code]), code

def test_check_cell_with_env_uses_library_check_off_the_loop_and_not_the_kernel(monkeypatch, abhyasa_cfg):
    key, seen, real = ready_env(), [], exercise.library_check
    monkeypatch.setattr(exercise, 'library_check', lambda *a: seen.append((a[1:], threading.current_thread() is threading.main_thread())) or real(*a))
    nb, code = library_cell(key, WRONG)
    v = asyncio.run(check_cell(nb, code, asyncio.Lock(), no_kernel))
    assert seen == [((WRONG, key), False)] and code.execution_count is None
    assert v['state'] == 'done' and [c['status'] for c in v['checks']] == ['fail', 'fail'] and v['checks'][0]['got'] == '999777'
    assert code.extra['exercise']['state']['last']['passed'] == 0 and nb.dirty

def test_a_deleted_environment_refuses_without_install_and_clears_an_earlier_pass(monkeypatch, abhyasa_cfg):
    monkeypatch.setattr(tools, 'make_tool_env', no_install)
    key = ready_env()
    nb, code = library_cell(key, GOOD)
    assert asyncio.run(check_cell(nb, code, asyncio.Lock(), no_kernel))['passed'] == 2 and code.extra['exercise']['state']['passed']
    shutil.rmtree(tool_dir(key))
    with pytest.raises(Refused) as e: asyncio.run(check_cell(nb, code, asyncio.Lock(), no_kernel))
    assert str(e.value) == JUDGE['no_env'] == 'This lesson needs its tool environment. Make it again from the lesson.'
    s = code.extra['exercise']['state']
    assert s['passed'] is False and s['last'] is None
    with pytest.raises(Refused, match='check_exercise first'): grade_cell(nb, code, asyncio.Lock(), 8, 'Fine.')

@pytest.fixture
def lesson(tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from leela.blocks.agent.ai import _session_tools
    from leela.workspace import Workspace
    monkeypatch.setattr(tools, 'make_tool_env', no_install)
    key, p = ready_env(), tmp_path/'lesson.ipynb'
    task, code = exercise_cells(SPEC | dict(env=key))
    Notebook([task, code]).save(p)
    ws = Workspace(roots=[tmp_path], approvals='auto', python=sys.executable)
    ws.open(p)
    try:
        with TestClient(ide_app(ws)) as client:
            client.get('/tab/state')
            _, live, _ = ws.docstore.owner(str(p))
            yield client, p, live, code, key, {f.__name__: f for f in _session_tools(ws.inline_ai.host)}
    finally: ws.shutdown_now()

def test_a_deleted_environment_gives_the_recovery_message_on_the_route_and_the_agent_tool(lesson, abhyasa_cfg):
    client, p, live, code, key, agent = lesson
    body = dict(path=str(p), i=1, id=code.id, source=GOOD)
    got = client.post('/exercise/check', json=body).json()
    assert got['passed'] == 2 and live[1].execution_count is None and live[1].extra['exercise']['state']['passed']
    for hidden in ('-246', '-123'): assert hidden not in json.dumps(got)
    shutil.rmtree(tool_dir(key))
    r = client.post('/exercise/check', json=dict(body, seq=100))
    assert r.status_code == 409 and r.json() == dict(ok=False, error=JUDGE['no_env'])
    assert agent['check_exercise'](str(p), code.id) == JUDGE['no_env']
    assert live[1].extra['exercise']['state']['passed'] is False and live[1].execution_count is None
    assert 'check_exercise first' in agent['grade_exercise'](str(p), code.id, 8, 'Fine.')

@pytest.fixture
def add(tmp_path):
    from leela.blocks.agent.ai import WorkspaceHost, _session_tools
    from leela.blocks.fs.fs import Sandbox
    path = tmp_path/'lesson.ipynb'
    Notebook([Cell(source='before')]).save(path)
    host = WorkspaceHost(SimpleNamespace(fs=Sandbox([tmp_path]), project_root=tmp_path))
    return {f.__name__: f for f in _session_tools(host)}['add_exercise'], path

def test_add_exercise_with_packages_finds_or_makes_the_environment_then_checks_in_it(add, monkeypatch, abhyasa_cfg):
    f, path = add
    made, seen, real = [], [], exercise.library_check
    monkeypatch.setattr(tools, 'make_tool_env', lambda names: made.append(names) or AttrDict(key=ready_env(names), ok=True, error=''))
    monkeypatch.setattr(exercise, 'library_check', lambda *a: seen.append(a[2]) or real(*a))
    assert f(str(path), **SPEC, solution=SECRET, packages=['six']).startswith('Added the exercise')
    key = tool_key(['six'])
    assert made == [['six']] and seen == [key, key]
    assert Notebook.load(path).cells[-1].extra['exercise']['env'] == key and 'SECRET_REFERENCE' not in path.read_text()
    assert f(str(path), **SPEC, solution=SECRET, packages=['six']).startswith('Added the exercise') and made == [['six']]
    assert f(str(path), **SPEC, solution='def double(x): return 4', packages=['six']) == 'the solution fails: A negative number'

def test_add_exercise_with_packages_refuses_a_failed_install_or_a_bad_name(add, monkeypatch):
    f, path = add
    before = path.read_bytes()
    monkeypatch.setattr(tools, 'make_tool_env', lambda names: AttrDict(key=tool_key(names), ok=False, error='six has no wheel for this computer, so Leela cannot install it.'))
    assert f(str(path), **SPEC, solution=SECRET, packages=['six']) == 'add_exercise failed: six has no wheel for this computer, so Leela cannot install it.'
    monkeypatch.setattr(tools, 'make_tool_env', no_install)
    assert f(str(path), **SPEC, solution=SECRET, packages=['--index-url=https://x']).startswith('add_exercise failed: ValueError: package:')
    assert f(str(path), **{**SPEC, 'fname': 'not a name'}, solution=SECRET, packages=['six']).startswith('add_exercise failed')
    assert path.read_bytes() == before
