import subprocess, threading, time
from pathlib import Path
from types import SimpleNamespace
import pytest
from leela.blocks.learn import tools
from leela.blocks.learn.tools import NO_UV, TOO_LONG, install_cmds, make_tool_env, tool_dir, tool_job, tool_key, tool_names, tool_python
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
