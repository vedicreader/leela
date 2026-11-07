"Runtimes: project kernels, tab bindings, run configurations, the debugger."

import json
import os
import shutil
from pathlib import Path
import pytest
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.blocks.runtime.kernels import project_python
from leela.workspace import Workspace
import asyncio
from fastcore.all import Path
from leela.blocks.runtime.devserver import DevServer, DevServers, infer_watch, run_command, split_cmd
from leela.blocks.runs.runs import RUNS_FILE, Run, Runs
from leela.blocks.debug.debug import DebugSession, debugpy_available
from kunda import support as support

def _client(root):
    ws = Workspace(roots=[root])
    return TestClient(ide_app(ws)), ws

@pytest.mark.makes_venv
@pytest.mark.skipif(not shutil.which('uv'), reason='needs uv to create an environment')
def test_creating_the_environment_produces_a_usable_interpreter(tmp_path):
    "The real thing: uv makes a venv, leela adopts it, and the route reports it."
    (tmp_path/'main.py').write_text('print(1)')
    client, ws = _client(tmp_path)
    with client as c:
        r = c.post('/runtime/create')
        assert r.status_code == 200, r.text
        made = r.json()['python']
        after = c.get('/runtime/info').json()
    assert (tmp_path/'.venv').is_dir()
    assert made == project_python([tmp_path]), 'what it made is what discovery finds'
    from leela.blocks.runtime.kernels import python_for
    assert python_for(tmp_path, ws) == made and ws.pool.default_python is None, 'found as the project venv, not chosen for every folder'
    assert after['needs_create'] is False

def _venv(root):
    "A venv whose `python` is executable, since /runtime/info really runs it."
    py = root/'.venv'/'bin'/'python'
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_text('#!/bin/sh\nexit 1\n'); py.chmod(0o755)
    return py

def test_a_terminal_uses_the_venv_of_the_folder_it_opened_in(tmp_path):
    "One workspace, several checkouts, one environment each."
    from leela.app import _term_python
    a, b = tmp_path/'repo-a', tmp_path/'repo-b'
    pa, pb = _venv(a), _venv(b)
    ws = Workspace(roots=[a, b])
    assert ws.pool.default_python is None, 'no folder is chosen for the others'
    assert _term_python(ws, b) == str(pb), 'a terminal in repo-b belongs in repo-b'
    assert _term_python(ws, a) == str(pa)

def test_a_terminal_finds_a_venv_that_appeared_after_the_workspace_was_built(tmp_path):
    "default_python is None until something chooses; a shell must not fall back to PATH."
    from leela.app import _term_python
    ws = Workspace(roots=[tmp_path])
    assert ws.pool.default_python is None
    py = _venv(tmp_path)
    assert _term_python(ws, tmp_path) == str(py)
    assert _term_python(ws, None) == str(py), 'discovery over the roots, not the bare PATH'

def test_a_release_runs_in_the_venv_of_the_project_being_released(tmp_path):
    "The reported failure: `nbdev_prepare` from a system Python 3.8."
    from leela.blocks.pipelines.pipelines import Release
    from leela.blocks.runtime.kernels import python_for
    a, b = tmp_path/'repo-a', tmp_path/'repo-b'
    pa, pb = _venv(a), _venv(b)
    ws = Workspace(roots=[a, b])
    assert ws.pool.default_python is None, 'no folder is chosen for the others'
    assert python_for(b, ws) == str(pb), 'a release of repo-b belongs in repo-b'
    p = Release(b, python=python_for(b, ws))
    env = p._env()
    assert env['PATH'].split(os.pathsep)[0] == str(pb.parent)
    assert env['VIRTUAL_ENV'] == str(b/'.venv')

def test_find_repos_matches_a_linked_worktree_whose_git_is_a_file(tmp_path):
    "A worktree's `.git` is a file pointing at the real one. It is still somewhere to open."
    from leela.blocks.git.repos import find_repos
    wt = tmp_path/'checkouts'/'feature-branch'
    wt.mkdir(parents=True)
    (wt/'.git').write_text('gitdir: /elsewhere/.git/worktrees/feature-branch\n')
    assert [p.name for p in find_repos(tmp_path)] == ['feature-branch']

def test_the_runtime_list_is_asked_of_ramabana_not_duplicated(tmp_path):
    "leela's copy of the runtime list drifted twice."
    from leela.blocks.agent.models import runtimes
    from leela.agent.core import RUNTIME_NAMES, runtime_available
    got = {r['value']: r['available'] for r in runtimes()}
    assert tuple(got) == RUNTIME_NAMES, 'exactly what register_model accepts, in its order'
    for name, avail in got.items():
        assert avail is bool(runtime_available(name)), f'{name} must report what rishi says'
    assert got['remote'] is True

def test_the_default_turn_model_resolves_without_claude_code_on_path(tmp_path, monkeypatch):
    "CI has no `claude`; 41 scripted-backend tests failed there resolving `claude-opus-5-5` before any fake answered."
    from leela.agent.core import DFLT_TURN
    monkeypatch.setenv('PATH', str(tmp_path))
    assert shutil.which('claude') is None
    assert Workspace(roots=[tmp_path]).ai.model.name == DFLT_TURN

@pytest.mark.no_claude
def test_without_claude_code_the_agent_panel_says_why_rather_than_failing(tmp_path, monkeypatch):
    "ramabana's `resolve` raised for `claude-opus-5-5` without `claude` on PATH, so the assistant, `/agent/history` and a turn raised."
    from leela.agent.core import DFLT_SMALL, DFLT_TURN
    monkeypatch.setenv('PATH', str(tmp_path))
    for k in ('LEELA_MODEL', 'RAMABANA_MODEL', 'LEELA_MODEL_INLINE', 'RAMABANA_MODEL_INLINE'): monkeypatch.delenv(k, raising=False)
    assert shutil.which('claude') is None
    ws = Workspace(roots=[tmp_path]); ws._state_path = tmp_path/'ws.json'
    assert ws.ai.model.name == DFLT_TURN and ws.ai.model.missing
    with TestClient(ide_app(ws)) as c:
        r = c.get('/agent/history')
        assert r.status_code == 200, r.text
        d = r.json()
        assert d['model'] == DFLT_TURN and d['unavailable'], d
        r = c.post('/agent/ask', json={'prompt': 'hello'})
        assert r.status_code == 200, r.text
        d = r.json()
        assert not d['ok'] and d['text'] and d['model'] == DFLT_TURN, d
        m = c.get('/agent/models').json()
        assert any(r.get('unavailable') and r['value'] == DFLT_TURN for r in m['models']), m
    assert ws.inline_ai.model.name == DFLT_SMALL and ws.inline_ai.ask('hello')

def test_choosing_the_litert_accelerator_is_remembered_and_exported(tmp_path, monkeypatch):
    """ramabana reads $LEELA_LITERT_BACKEND when it builds an engine."""
    monkeypatch.setenv('LEELA_LITERT_BACKEND', 'cpu')
    ws = Workspace(roots=[tmp_path]); ws._state_path = tmp_path/'ws.json'
    with TestClient(ide_app(ws)) as c:
        assert c.post('/agent/settings', json={'litert_backend': 'gpu'}).json()['litert_backend'] == 'gpu'
    assert os.environ['LEELA_LITERT_BACKEND'] == 'gpu' and ws.litert_backend == 'gpu'
    assert ws.state()['litert_backend'] == 'gpu', 'and it is written to the workspace'
    monkeypatch.delenv('LEELA_LITERT_BACKEND', raising=False)
    again = Workspace.load(path=ws._state_path)
    assert again.litert_backend == 'gpu'
    assert os.environ['LEELA_LITERT_BACKEND'] == 'gpu', 'restored before any engine is built'

def test_the_finder_skips_the_directories_that_made_it_slow(tmp_path):
    "Object stores, virtualenvs and caches never hold a checkout worth opening."
    from leela.blocks.git.repos import find_repos
    good = tmp_path/'work'/'real-repo'
    (good/'.git').mkdir(parents=True); (good/'.git'/'HEAD').write_text('ref: x')
    for junk in ('node_modules/vendored', '.venv/src/pkg', '.cache/thing'):
        d = tmp_path/junk
        (d/'.git').mkdir(parents=True); (d/'.git'/'HEAD').write_text('ref: x')
    assert [p.name for p in find_repos(tmp_path)] == ['real-repo']

@pytest.mark.makes_venv
def test_the_interpreter_and_a_new_venv_follow_the_chosen_folder(tmp_path):
    "With two folders open, the picker described the first one and created into it."
    a, b = tmp_path/'first', tmp_path/'second'
    for d in (a, b): (d/'src').mkdir(parents=True)
    py = a/'.venv'/'bin'/'python'
    py.parent.mkdir(parents=True)
    py.write_text('#!/bin/sh\nexit 1\n'); py.chmod(0o755)
    ws = Workspace(roots=[a, b])
    with TestClient(ide_app(ws)) as c:
        assert c.get('/runtime/info').json()['root'] == str(a), 'precondition: the first folder'
        ws.activate_root(b)
        info = c.get('/runtime/info').json()
        assert info['root'] == str(b), 'the chosen folder, not the first'
        assert info['needs_create'] is True, "and it reports b's absence, not a's venv"
        created = c.post('/runtime/create').json()
        assert created['root'] == str(b) and created['python'].startswith(str(b))
        assert (b/'.venv').is_dir() and not (a/'.venv'/'pyvenv.cfg').exists(), 'nothing landed in a'

@pytest.mark.makes_venv
def test_a_folder_of_clones_creates_the_venv_in_the_checkout_being_worked_in(tmp_path):
    """`orgs` open as one folder: the environment panel described `orgs` and offered to create a `.venv` beside the clones."""
    import subprocess
    orgs = tmp_path/'orgs'
    a = orgs/'dockeasy'; (a/'nbs').mkdir(parents=True)
    subprocess.run(['git', 'init', '-q', str(a)], check=True)
    _notebook(a/'nbs'/'00_core.ipynb')
    ws = Workspace(roots=[orgs])
    with TestClient(ide_app(ws)) as c:
        assert c.get('/runtime/info').json()['root'] == str(orgs), 'nothing open, so the open folder'
        ws.open(a/'nbs'/'00_core.ipynb')
        info = c.get('/runtime/info').json()
        assert info['root'] == str(a), 'the checkout the notebook is in'
        assert info['needs_create'] is True and info['python'] == ''
        created = c.post('/runtime/create').json()
    assert created['root'] == str(a) and (a/'.venv').is_dir()
    assert not (orgs/'.venv').exists(), 'nothing landed beside the clones'

def test_run_configurations_belong_to_the_checkout_not_the_folder_of_clones(tmp_path):
    "A release, a run and an interpreter are all the same question, and have to give one answer."
    import subprocess
    orgs = tmp_path/'orgs'
    a, b = orgs/'repo-a', orgs/'repo-b'
    for d in (a, b):
        d.mkdir(parents=True)
        subprocess.run(['git', 'init', '-q', str(d)], check=True)
        (d/'main.py').write_text('print(1)\n')
    ws = Workspace(roots=[orgs])
    assert ws.project_repo == orgs, 'with nothing open, the folder that is open'
    ws.open(a/'main.py')
    assert ws.project_repo == a and Path(ws.runs.root) == a
    ws.open(b/'main.py')
    assert ws.project_repo == b and Path(ws.runs.root) == b, 'and it follows the file'
    assert Path(Workspace(roots=[a]).project_repo) == a, 'a checkout opened directly is itself'

def test_one_walk_answers_where_the_project_is(tmp_path):
    "The interpreter, the index and the release all ask this, so they ask it in one place."
    from leela.core.projects import nearest_marked, project_dir
    root = tmp_path/'repo'; (root/'nbs').mkdir(parents=True)
    (root/'pyproject.toml').write_text('[project]\nname = "x"\n')
    assert project_dir(root/'nbs') == root
    assert project_dir(tmp_path) is None, 'a folder that is not a checkout is not one'
    assert project_dir(root/'nbs', stop=root/'nbs') is None, 'the walk does not pass the open folder'
    py = _venv(root)
    assert nearest_marked(root/'nbs', ['.venv/bin/python'])[1] == py, 'the marker found comes back'

def test_the_path_prelude_is_written_in_the_users_own_shell():
    "`export FOO=bar` is not fish, and fish has no `export` at all."
    from leela.blocks.term.term import path_prelude
    clear = "printf '\\033[H\\033[2J\\033[3J'"
    assert path_prelude('/p/.venv/bin/python', '/opt/homebrew/bin/fish') == \
        " set -gx PATH /p/.venv/bin $PATH; printf '\\e[H\\e[2J\\e[3J'"
    assert path_prelude('/p/.venv/bin/python', '/bin/bash') == ' export PATH="/p/.venv/bin:$PATH"; ' + clear
    assert path_prelude('/p/.venv/bin/python', '/bin/zsh') == ' export PATH="/p/.venv/bin:$PATH"; ' + clear
    assert path_prelude('/p/.venv/bin/python', '/bin/tcsh') == ' setenv PATH "/p/.venv/bin:$PATH"; ' + clear
    assert path_prelude('', '/bin/bash') == '', 'no interpreter, nothing to prepend'
    for shell in ('/bin/bash', '/opt/homebrew/bin/fish'):
        assert path_prelude('/p/.venv/bin/python', shell).startswith(' '), 'kept out of history'

def test_opening_a_terminal_really_builds_its_argv_from_the_settings(tmp_path):
    "Actually open the pty, because nothing else here does."
    settings = tmp_path/'.leela'/'settings.json'
    settings.parent.mkdir()
    settings.write_text(json.dumps({'terminal': {
        'shell': '/bin/echo', 'shellArgs': ['leela-terminal-ok'], 'loginShell': False}}))
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as c:
        info = c.get('/term/info').json()
        if not info['enabled']: pytest.skip(info['why'])
        try:
            with c.websocket_connect('/term/ws') as sock:
                sock.send_json({'token': info['token'], 'kind': 'shell', 'id': 'probe',
                                'cwd': str(tmp_path), 'cols': 80, 'rows': 24})
                first = sock.receive()
                assert 'bytes' in first, f'setup failed instead of starting a pty: {first}'
                assert b'leela-terminal-ok' in first['bytes']
        finally:
            ws.terms.close_all()

def test_the_picker_lists_the_venvs_of_repos_inside_one_open_folder(tmp_path):
    """A folder of checkouts opened as one root: the kernel already ran in the repo's own venv, but the picker only scanned the root itself, so that interpreter was neither listed nor marked."""
    orgs = tmp_path/'orgs'; orgs.mkdir()
    _venv(orgs)
    pb = _venv(orgs/'dockeasy')
    (orgs/'dockeasy'/'nbs').mkdir(parents=True)
    nb = orgs/'dockeasy'/'nbs'/'00_core.ipynb'
    nb.write_text('{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}')
    ws = Workspace(roots=[orgs])
    opts = ws.kernel_options(ws.open(nb))
    assert opts['python'] == str(pb), 'the notebook runs in its own repo\'s venv'
    assert str(pb) in [p['path'] for p in opts['pythons']], 'and the picker offers it'
    assert [p['path'] for p in opts['pythons'] if p['current']] == [str(pb)], 'and marks it'

def _notebook(path):
    path.write_text('{"nbformat":4,"nbformat_minor":5,"metadata":{},"cells":[]}')

def test_run_environment_file_is_confined_and_overlaid_by_explicit_values(tmp_path):
    (tmp_path/'.env.local').write_text('TOKEN="from file"\nPORT=8000\nexport DEBUG=true\n')
    run = Run('api', 'python app.py', env={'PORT': '9000'}, env_file='.env.local')
    assert run.resolved_env(tmp_path) == {'TOKEN': 'from file', 'PORT': '9000', 'DEBUG': 'true'}
    run.env_file = '../outside.env'
    with pytest.raises(ValueError, match='outside the project'):
        run.resolved_env(tmp_path)

def test_a_broken_configurations_file_is_a_note_not_a_crash(tmp_path):
    "A typo in a project file must not stop the IDE opening the project."
    (tmp_path/'.leela').mkdir()
    (tmp_path/RUNS_FILE).write_text('{"runs": [oops]}')
    r = Runs(tmp_path)
    assert r.runs == [] and r.note

def test_a_run_configuration_becomes_a_watched_process():
    assert split_cmd('uvicorn app:app --port 8000') == ['uvicorn', 'app:app', '--port', '8000']
    assert split_cmd(['python', '-m', 'x']) == ['python', '-m', 'x']
    assert infer_watch(['uvicorn', 'app:app', '--port', '8000']) == 'app'
    assert infer_watch(['gunicorn', '-w', '4', 'server:application']) == 'server'
    assert infer_watch(['python', 'train.py']) == 'train'
    assert infer_watch(['pytest', '-x']) == ''
    assert DevServers.key('uvicorn app:app --port 8000') != DevServers.key('uvicorn app:app --port 8001')
    assert DevServers.key('./x.py') == DevServers.key(str(Path('x.py').resolve()))
    state = DevServer(script='python x.py').state()
    assert state['returncode'] is None and state['started'] is None and state['ended'] is None
    with pytest.raises(SystemExit): run_command(['definitely-not-installed', '--x'])

def test_a_command_runs_in_this_process(tmp_path, monkeypatch, capsys):
    "The whole point: the command runs *here*, where the inspector is."
    p = tmp_path/'job.py'
    p.write_text("import sys; print('ran', sys.argv[1:])\n")
    monkeypatch.chdir(tmp_path)
    run_command(['python', str(p), '--flag'])
    assert "ran ['--flag']" in capsys.readouterr().out

def test_direct_debugpy_stops_exposes_locals_and_continues(tmp_path):
    python = shutil.which('python')
    if not python or not debugpy_available(python): pytest.skip('debugpy is not installed in the test interpreter')
    source = tmp_path/'direct_debug.py'
    source.write_text('value = 41\nanswer = value + 1\nprint(answer)\n')
    session = DebugSession(python, tmp_path).start_adapter()
    try:
        session.launch({'request':'launch', 'program':str(source), 'justMyCode':True},
                       {str(source): [2]})
        event = session.wait_event('stopped', 15)
        state = session.state(event['body']['threadId'])
        assert state['frames'][0]['line'] == 2
        assert any(v['name'] == 'value' and v['value'] == '41' for v in state['variables'])
        assert session.evaluate('value + 1')['result'] == '42'
        session.control('continue')
        assert session.wait_event({'exited', 'terminated'}, 15)['event'] in ('exited', 'terminated')
    finally:
        session.disconnect()

def test_the_environment_leela_wires_up_actually_imports():
    state = support.kernel_support(__import__('sys').executable)
    assert state['ipykernel']['available'], state
    assert state['ipymini']['available'], state

def test_the_runs_file_follows_the_folder_you_chose(tmp_path):
    "The bug git had, in the runs surface: open one folder, add a second, switch, runs stayed behind."
    a, b = tmp_path/'leela', tmp_path/'cassowary'
    a.mkdir(); b.mkdir()
    ws = Workspace(roots=[a, b])
    assert ws.runs.root == a, 'precondition: the first folder'
    with TestClient(ide_app(ws)) as client:
        assert client.get('/runs').json()['path'].startswith(str(a))
        assert client.post('/workspace/activate', json={'path': str(b)}).json()['ok'] is True
        assert client.get('/runtime/info').json()['root'] == str(b)
        assert client.get('/runs').json()['path'].startswith(str(b)), 'the chosen folder, not the first'
    assert ws.runs.root == b

SCRATCH_RUNS = """\
import sys
print('hello from the run')
sys.exit({code})
"""

async def _finished(s, tries=80):
    "Start `s` and wait for its command to return; the inspector keeps the process up after."
    await s.start()
    for _ in range(tries):
        if not s.running: break
        await asyncio.sleep(0.2)
    return s

def test_a_run_reports_the_command_not_the_inspector(tmp_path):
    """The child keeps the inspector up after the command returns, so process liveness says nothing about whether the app is running."""
    p = tmp_path/'boom.py'; p.write_text(SCRATCH_RUNS.format(code=3))
    s = asyncio.run(_finished(DevServer(script=str(p), port=9471)))
    try:
        assert s.alive, 'the inspector outlives the command, by design'
        assert not s.running and s.command_code == 3, 'but the command is over, and it failed'
        assert s.state()['code'] == 3 and s.state()['running'] is False
        assert any('hello from the run' in l for l in s.tail(20)), 'its output was captured'
        assert any('SystemExit: 3' in l for l in s.tail(20)), 'and so was why it stopped'
    finally: asyncio.run(s.stop())

SERVER_RUN = """\
import time
print('Uvicorn running on http://127.0.0.1:{port}', flush=True)
print('also listening on http://127.0.0.1:{port2}', flush=True)
while True: time.sleep(0.1)
"""

def test_stopping_a_run_ends_its_viewers_and_starting_again_is_a_fresh_stream(tmp_path):
    """Stop then Run: the viewer's queue was left open on the dead server, and the new server had no viewer, so the terminal froze on the first run's output."""
    p = tmp_path/'srv.py'; p.write_text(SERVER_RUN.format(port=8765, port2=8766))
    async def go():
        dev = DevServers(port=9474)
        s1 = await dev.start(str(p))
        q = s1.subscribe()
        # Bounded by the `wait_for` below, not by a count: under `-n auto` the child's own start can take longer than 5 s.
        while len(s1.urls) < 2: await asyncio.sleep(0.1)
        assert s1.urls == ['http://127.0.0.1:8765', 'http://127.0.0.1:8766'], 'every URL a run prints, not the first'
        assert s1.app_url == 'http://127.0.0.1:8765'
        await dev.stop(str(p))
        assert s1._reader.done() and s1.ended is not None, 'stop returns after its reader has finished'
        got = []
        while not q.empty(): got.append(q.get_nowait())
        assert got and got[-1] is None, 'the viewer is told the run ended'
        assert not s1._subs, 'and is no longer subscribed to a dead server'
        assert s1.state()['last_url'] == 'http://127.0.0.1:8765', 'a stopped run remembers where it was'
        late = s1.subscribe(); items = [late.get_nowait() for _ in range(late.qsize())]
        assert items[0] and items[-1] is None, 'a late viewer of a finished run is primed, then told it ended'
        s2 = await dev.start(str(p))
        assert s2 is not s1 and s2.pid != s1.pid
        q2 = dev.get(str(p)).subscribe()
        seen = bytearray()
        while b'Uvicorn running' not in seen:
            assert (chunk := await q2.get()) is not None, 'the new run ended before it printed'
            seen += chunk
        await dev.stop_all()
    asyncio.run(asyncio.wait_for(go(), 60))

def test_the_run_socket_says_exit_when_the_run_is_stopped(tmp_path):
    "`/run/ws` used to hang on an empty queue forever, so the browser never learned the run ended."
    p = tmp_path/'srv.py'; p.write_text(SERVER_RUN.format(port=8767, port2=8768))
    ws = Workspace(roots=[tmp_path], dev_port=9476)
    with TestClient(ide_app(ws)) as c:
        info = c.get('/term/info').json()
        if not info['enabled']: pytest.skip(info['why'])
        r = c.post(f'/dev/start?path={p}').json()
        assert r['ok'], r
        try:
            with c.websocket_connect('/run/ws') as sock:
                sock.send_json({'token': info['token'], 'kind': 'run', 'cwd': str(p), 'cols': 80, 'rows': 24})
                first = sock.receive()
                assert 'bytes' in first, f'setup failed instead of attaching: {first}'
                seen = first['bytes']
                while b'http://127.0.0.1:8768' not in seen:
                    frame = sock.receive()
                    assert 'bytes' in frame, frame
                    seen += frame['bytes']
                c.post(f'/dev/stop?path={p}')
                for _ in range(200):
                    m = sock.receive()
                    if 'text' in m: break
                assert json.loads(m['text'])['t'] == 'exit'
            listed = c.get('/dev/list').json()['servers'][0]
            assert listed['running'] is False and listed['last_url'] == 'http://127.0.0.1:8767'
            assert listed['urls'] == ['http://127.0.0.1:8767', 'http://127.0.0.1:8768']
        finally: c.post(f'/dev/stop?path={p}')

def test_the_stop_button_stops_a_run_when_no_kernel_is_open(tmp_path):
    "The toolbar's stop calls /kernel/interrupt. With only a run up it answered 'no running kernel' and left the server and its inspector alive."
    p = tmp_path/'srv.py'; p.write_text(SERVER_RUN.format(port=8769, port2=8770))
    ws = Workspace(roots=[tmp_path], dev_port=9477)
    with TestClient(ide_app(ws)) as c:
        if not c.get('/term/info').json()['enabled']: pytest.skip('no pty here')
        assert c.post(f'/dev/start?path={p}').json()['ok']
        try:
            r = c.get('/kernel/interrupt').json()
            assert r.get('ok'), r
            listed = c.get('/dev/list').json()['servers'][0]
            assert not listed['alive'] and listed['running'] is False, listed
        finally: c.post(f'/dev/stop?path={p}')

def test_the_stop_button_stops_a_run_beside_an_idle_kernel(tmp_path):
    "A notebook tab's kernel open but idle: stop ends the run, and the kernel is not interrupted. It used to interrupt the idle kernel and leave the run up."
    p = tmp_path/'srv.py'; p.write_text(SERVER_RUN.format(port=8771, port2=8772))
    ws = Workspace(roots=[tmp_path], dev_port=9478)
    hit = []
    class Idle:
        alive = True
        async def interrupt(self): hit.append('interrupt')
    ws.runtime_peek = lambda tab=None: Idle()
    with TestClient(ide_app(ws)) as c:
        if not c.get('/term/info').json()['enabled']: pytest.skip('no pty here')
        assert c.post(f'/dev/start?path={p}').json()['ok']
        try:
            r = c.get('/kernel/interrupt').json()
            assert r.get('ok') and 'stopped' in r.get('note', ''), r
            assert not c.get('/dev/list').json()['servers'][0]['alive']
            assert hit == [], 'the idle kernel was interrupted'
        finally: c.post(f'/dev/stop?path={p}')

def _alive_after(tmp_path, body, port, wait=8.0):
    "Run `body` as a script under the inspector; whether its process is still up `wait` seconds later."
    import time
    p = tmp_path/'s.py'; p.write_text(body)
    ws = Workspace(roots=[tmp_path], dev_port=port)
    with TestClient(ide_app(ws)) as c:
        if not c.get('/term/info').json()['enabled']: pytest.skip('no pty here')
        c.post(f'/dev/start?path={p}')
        try:
            end = time.monotonic() + wait
            while time.monotonic() < end:
                s = c.get('/dev/list').json()['servers'][0]
                if not s['alive']: return False
                time.sleep(0.2)
            return True
        finally: c.post(f'/dev/stop?path={p}')

def test_a_command_that_exits_cleanly_takes_its_inspector_with_it(tmp_path):
    "Exit 0, as uvicorn returns on Ctrl-C: the process ends. It used to idle with the inspector up and its ports held."
    assert not _alive_after(tmp_path, 'print("done")\n', 9479)

def test_a_command_that_crashes_keeps_its_inspector_for_a_look(tmp_path):
    "A crash keeps the inspector up, so the variable panel can show what went wrong."
    assert _alive_after(tmp_path, 'x = 1\nraise ValueError("boom")\n', 9480, wait=4.0)

def test_a_notebook_gets_its_own_repos_venv_without_being_asked(tmp_path):
    """Two folders open, each with an environment."""
    a, b = tmp_path/'first', tmp_path/'second'
    a.mkdir(); b.mkdir()
    pa, pb = _venv(a), _venv(b)
    (b/'nb.ipynb').write_text('{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}')
    ws = Workspace(roots=[a, b])
    assert ws.pool.default_python is None, "the first folder's venv is not every folder's default"

    tab = ws.open(str(b/'nb.ipynb'))
    opts = ws.kernel_options(tab)
    assert opts['python'] == str(pb), 'the picker names the venv this notebook actually runs in'
    current = [p['path'] for p in opts['pythons'] if p['current']]
    assert current == [str(pb)], 'and marks it selected, so there is nothing to choose'

    # ...which is the interpreter `Workspace.kernel` would have started it under all along.
    from leela.blocks.runtime.kernels import python_for
    assert python_for(ws.cwd_for(tab), ws) == str(pb)

    # ...and a tab in the first folder still answers with the first folder's.
    (a/'x.py').write_text('x = 1\n')
    assert ws.kernel_options(ws.open(str(a/'x.py')))['python'] == str(pa)

def test_closing_the_last_tab_of_a_folder_closes_its_kernel(tmp_path):
    """Only private kernels were closed on `/tab/close`, so a folder kernel outlived every tab that used it."""
    proj, other = tmp_path/'proj', tmp_path/'other'
    proj.mkdir(); other.mkdir()
    a, b = other/'a.py', other/'b.py'
    a.write_text('a = 1\n'); b.write_text('b = 2\n')
    nb = other/'n.ipynb'; _notebook(nb)
    ws = Workspace(roots=[proj, other])
    closed = []
    async def fake_close(key): closed.append(key)
    ws.pool.close = fake_close
    ws.open(a); ws.open(b); ws.open(nb)
    folder, private = ws.kernel_key(ws.tabs[0]), ws.kernel_key(ws.tabs[2])
    assert folder == str(other) and private == f'tab:{nb}'
    with TestClient(ide_app(ws)) as client:
        client.post(f'/tab/close?i=2')                    # the notebook: its key names only itself
        assert closed == [private]
        client.post(f'/tab/close?i=1')                    # b.py: a.py still holds the folder kernel
        assert closed == [private]
        client.post(f'/tab/close?i=0')                    # a.py: the last tab of that folder
        assert closed == [private, folder]

def test_nothing_a_page_load_asks_for_starts_a_kernel(tmp_path):
    """Opening Leela booted Python whether or not anybody ran anything."""
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from leela.workspace import Workspace
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        info = client.get('/kernel/info').json()
        assert info['alive'] is False and info['pid'] is None
        assert info['key'], 'it still says which kernel it would be'
        variables = client.get('/vars').json()
        assert variables['groups'] == [] and variables['runtime'].endswith(':live')
        assert not ws.pool.kernels, 'a page load started a kernel'

class _FakeEngine:
    closed = False
    def close(self): self.closed = True

class _FakeBackend:
    "A backend as the engine broker sees one: a spec, kwargs to build from, and a chat or not."
    def __init__(self, spec): self.spec, self.kw, self.chat, self._tried = spec, {}, None, False
    def _runtime_kw(self): return dict(self.kw)

def _loaded_engine(monkeypatch, live):
    "One `mlx/qwen` engine in the process broker, with a session on it or with a chat that failed."
    from leela.agent.core import ModelSpec
    from leela.blocks.runtime import engines as eng
    class Chat:
        @classmethod
        def create_engine(cls, model_id=None, **kw): return _FakeEngine()
    monkeypatch.setattr(eng, '_chat_cls', lambda runtime: Chat)
    b, be = eng.EngineBroker(max_engines=3), _FakeBackend(ModelSpec('qwen', 'mlx', 'qwen', ctx=8000))
    engine = b.attach(be)
    be._tried, be.chat = True, object() if live else None
    monkeypatch.setattr(eng, '_BROKER', b)
    return engine, be    # the users are a WeakSet, so the caller holds the backend

def test_clearing_the_local_engines_releases_a_failed_models_weights(tmp_path, monkeypatch):
    """The weights of a dialog model whose chat failed are held until this asks for them."""
    engine, be = _loaded_engine(monkeypatch, live=False)
    with _client(tmp_path)[0] as c: r = c.post('/runtime/engines/clear', json={}).json()
    assert r['ok'] and r['live'] == 0 and r['freed'] == [{'runtime': 'mlx', 'model': 'qwen'}]
    assert engine.closed

def test_a_devserver_child_borrows_leelas_path_only_on_leelas_python():
    """`_boot_src` runs under the project's interpreter."""
    import sys
    from leela.blocks.runtime.devserver import _boot_src
    from leela.blocks.runtime.support import LEELA_PY
    guard = _boot_src(['/somewhere/leela']).split('from leela')[0]
    real = sys.version_info
    for minor, borrows in ((tuple(LEELA_PY), True), ((2, 7), False)):
        ns = {}
        sys.version_info = (*minor, 0, 'final', 0)
        try: exec(guard, ns)
        finally: sys.version_info = real
        try: assert ('/somewhere/leela' in sys.path) is borrows, minor
        finally:
            if '/somewhere/leela' in sys.path: sys.path.remove('/somewhere/leela')

def _orgs(tmp_path):
    "A folder of clones with a venv of its own, and a checkout `karma` inside it with none."
    import subprocess
    orgs = tmp_path/'orgs'
    karma = orgs/'karma'; (karma/'nbs').mkdir(parents=True)
    subprocess.run(['git', 'init', '-q', str(karma)], check=True)
    _notebook(karma/'nbs'/'a.ipynb')
    return orgs, karma, _venv(orgs)

def test_a_checkout_never_borrows_the_venv_of_the_folder_above_it(tmp_path):
    "`orgs/.venv` held kernel support only, and ran every checkout inside `orgs` that had no venv of its own."
    from leela.blocks.runtime.kernels import python_for
    orgs, karma, shared = _orgs(tmp_path)
    ws = Workspace(roots=[orgs])
    assert python_for(karma/'nbs', ws) is None, 'karma has no venv, and orgs/.venv is not its'
    assert python_for(karma/'nbs', None) is None, 'nor with no workspace to ask'
    (loose := orgs/'notes').mkdir()
    assert python_for(loose, ws) == str(shared), 'a folder in no checkout uses the open folder\'s own venv'
    tab = ws.open(str(karma/'nbs'/'a.ipynb'))
    assert ws.inline_ai.host._env(karma)['PATH'].split(os.pathsep)[0] != str(shared.parent), 'run_shell does not borrow it either'
    assert ws.kernel_options(tab)['python'] is None

def test_a_chosen_interpreter_wins_and_is_the_only_way_to_borrow(tmp_path):
    "The picker set one global default that a project's own venv then outranked, so choosing changed nothing."
    from leela.blocks.runtime.kernels import python_for
    orgs, karma, shared = _orgs(tmp_path)
    own = _venv(karma)
    ws = Workspace(roots=[orgs])
    tab = ws.open(str(karma/'nbs'/'a.ipynb'))
    assert python_for(ws.cwd_for(tab), ws) == str(own)
    o = asyncio.run(ws.set_kernel(python=str(shared), tab=tab, restart=False))
    assert o['python'] == str(shared) and o['chosen'], 'the choice beats the project venv'
    assert ws.pool.default_python is None, 'and is held for karma, not every folder'
    back = Workspace(roots=[orgs]); back.restore_settings(ws.state())
    assert python_for(karma/'nbs', back) == str(shared), 'a saved session keeps it'
    o = asyncio.run(ws.set_kernel(python='', tab=tab, restart=False))
    assert o['python'] == str(own) and not o['chosen'], 'clearing hands karma back to its own venv'

def _cell_nb(path):
    path.write_text(json.dumps({'cells': [{'cell_type': 'code', 'id': 'c0', 'source': 'x = 1', 'metadata': {}, 'outputs': [], 'execution_count': None}],
                                'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    return path

def _refused(r, proj, said=''):
    "The one answer every route gives a project with no venv."
    d = r.json()
    assert r.status_code >= 400 and d['kind'] == 'no_venv' and d['refs'] == [str(proj)], d
    assert d['error'] == (said or f'No Python environment for {proj.name}. Set up .venv or choose an interpreter.'), d

@pytest.mark.no_venv
def test_no_route_makes_a_venv_without_a_click(tmp_path, monkeypatch):
    "Leela made ~/Downloads/.venv on the first run in it, without asking."
    from leela.blocks.debug.debug import DebugSession
    orgs, karma, shared = _orgs(tmp_path)
    nb, main = _cell_nb(karma/'nbs'/'a.ipynb'), karma/'main.py'
    main.write_text('print(1)\n')
    made, seen = _made(monkeypatch), []
    monkeypatch.setattr(DebugSession, 'start_adapter', lambda self: seen.append(self.python))
    ws = Workspace(roots=[orgs]); ws.open(str(nb))
    with TestClient(ide_app(ws)) as c:
        assert c.get('/runtime/info').status_code == 200 and c.get('/kernel/options').json()['no_venv'], 'opening the folder makes nothing'
        assert not any(p['current'] for p in c.get('/kernel/options').json()['pythons']), "and Leela's own is not shown as in use"
        _refused(c.post('/nb/run/stream', json={'i': 0, 'id': 'c0', 'source': 'x = 1', 'path': str(nb)}), karma)
        _refused(c.post('/nb/run', json={'i': 0, 'id': 'c0', 'source': 'x = 1', 'path': str(nb)}), karma)
        _refused(c.post('/exec', json={'code': '1', 'path': str(nb)}), karma)
        ws.open(str(main))
        _refused(c.post('/run/code', json={'code': '1', 'path': str(main)}), karma)
        _refused(c.post('/dev/start', params={'path': str(main)}), karma)
        _refused(c.get('/debug/capabilities'), karma)
        _refused(c.post('/debug/install', json={'python': ''}), karma)
        _refused(c.post('/debug/start', json={'program': str(main), 'cwd': str(karma)}), karma)
        assert c.get('/vars').status_code == 200 and c.post('/agent/info').status_code < 500, 'background reads do not fail on it'
    assert made == [] and seen == [] and not (karma/'.venv').exists()

@pytest.mark.no_venv
def test_a_pipeline_in_a_uv_project_with_no_venv_runs_pullups_steps(tmp_path, monkeypatch):
    "Leela refused a release in a uv project with no .venv and skipped `uv run`; pullup's steps are uv's, and uv makes .venv."
    import time
    from leela.blocks.pipelines.app import _ship
    from leela.blocks.pipelines.pipelines import PipelineError
    orgs, fake, log = tmp_path/'orgs', tmp_path/'fake', tmp_path/'uv.log'
    lib = _checkout(orgs, 'lib'); (lib/'uv.lock').write_text('')
    (lib/'.leela').mkdir(); (lib/'.leela'/'release.json').write_text(json.dumps({'steps': [{'id': 'build', 'label': 'build', 'cmd': 'uv build'}]}))
    fake.mkdir(); (fake/'uv').write_text(f"#!/bin/sh\necho \"$@\" > '{log}'\n"); (fake/'uv').chmod(0o755)
    monkeypatch.setenv('PATH', str(fake))
    made = _made(monkeypatch)
    ws = Workspace(roots=[orgs])
    with TestClient(ide_app(ws)) as c:
        r = c.post('/releases/action', json={'op': 'start', 'repo': str(lib)})
        assert r.status_code == 200, r.json()
        for _ in range(500):
            if not (s := c.get('/releases', params={'repo': str(lib)}).json())['running']: break
            time.sleep(.02)
        assert s['steps'][0]['status'] == 'passed', s
        for path in ('/deploys/action', '/drive/action'):
            assert c.post(path, json={'op': 'step', 'step': 'nope', 'repo': str(lib)}).json().get('kind') != 'no_venv', path
    assert log.read_text().split() == ['run', '--project', str(lib.resolve()), 'uv', 'build'], 'the step is `uv run`, unchanged'
    with pytest.raises(PipelineError, match='fastship is not installed'): _ship(lib, ws, ['ship-bump'])
    assert made == [], 'Leela makes no venv; uv does, when a step needs one'

@pytest.mark.no_venv
def test_a_python_project_with_no_pyproject_and_no_venv_gets_a_plain_message(tmp_path, monkeypatch):
    "With no pyproject.toml there is no uv project to run in, so Leela says what is missing."
    orgs = tmp_path/'orgs'
    old, site = _checkout(orgs, 'old', py=False), _checkout(orgs, 'site', py=False)
    (old/'setup.py').write_text('')
    made = _made(monkeypatch)
    ws = Workspace(roots=[orgs])
    with TestClient(ide_app(ws)) as c:
        assert c.get('/releases', params={'repo': str(old)}).status_code == 200 and c.get('/drive', params={'repo': str(old)}).status_code == 200, 'looking at a panel is fine'
        for path, d in (('/releases/action', {'op': 'start'}), ('/deploys/action', {'op': 'step', 'step': 'x'}), ('/drive/action', {'op': 'step', 'step': 'x'})):
            _refused(c.post(path, json=d | {'repo': str(old)}), old, 'No pyproject.toml and no Python environment in old.')
        assert c.post('/drive/action', json={'op': 'step', 'step': 'nope', 'repo': str(site)}).json().get('kind') != 'no_venv', 'a project that is not Python needs no venv'
    assert made == [] and not (old/'.venv').exists() and not (site/'.venv').exists()

@pytest.mark.no_venv
def test_the_notice_shows_for_a_python_project_with_no_venv(tmp_path, monkeypatch):
    "There was no word that a project had nowhere to run its Python, only a venv Leela made."
    orgs, karma, shared = _orgs(tmp_path)
    (plain := orgs/'docs').mkdir(); (plain/'a.md').write_text('# a\n')
    ws = Workspace(roots=[orgs])
    with TestClient(ide_app(ws)) as c:
        ws.open(str(karma/'nbs'/'a.ipynb'))
        assert c.get('/kernel/info').json()['no_venv'] == {'root': str(karma), 'name': 'karma'}
        ws.open(str(plain/'a.md'))
        assert c.get('/kernel/info').json()['no_venv'] is None, 'docs is in orgs, which has a venv'
        ws.open(str(karma/'nbs'/'a.ipynb')); ws.choose_python(str(shared))
        assert c.get('/kernel/info').json()['no_venv'] is None, 'a chosen interpreter ends it'
    (folder := tmp_path/'Downloads').mkdir(); (folder/'photo.jpg').write_bytes(b'')
    ws = Workspace(roots=[folder])
    with TestClient(ide_app(ws)) as c:
        assert c.get('/kernel/info').json()['no_venv'] is None, 'a folder with no Python in it gets no notice'
        (folder/'s.py').write_text('')
        assert c.get('/kernel/info').json()['no_venv']['name'] == 'Downloads', 'one .py at the top is Python content'
    assert Workspace(roots=[]).venv_notice() is None and Workspace(roots=[]).user_python(tmp_path) is None, 'a loose file keeps Leela\'s Python'

@pytest.mark.no_venv
def test_set_up_venv_makes_it_and_ends_the_notice(tmp_path, monkeypatch):
    "The person's click is the only thing that makes a venv, and Leela says so after."
    import kunda.support as ks
    orgs, karma, shared = _orgs(tmp_path)
    def fake(root, python=None):
        made.append(Path(root)); py = _venv(Path(root)); (Path(root)/'.venv'/'pyvenv.cfg').write_text('home = /x\nversion_info = 3.13.1\n')
        return str(py)
    made = []
    monkeypatch.setattr(ks, 'make_venv', fake)
    ws = Workspace(roots=[orgs]); ws.open(str(karma/'nbs'/'a.ipynb'))
    with TestClient(ide_app(ws)) as c:
        assert c.get('/kernel/info').json()['no_venv']['root'] == str(karma)
        r = c.post('/runtime/create', json={'root': str(karma)}).json()
        assert made == [karma] and r['python'] == str(karma/'.venv'/'bin'/'python'), r
        assert r['note'] == 'Leela set up .venv for karma (Python 3.13). Change it in kernel settings.'
        assert c.get('/kernel/info').json()['no_venv'] is None and ws.kernel_options()['venv_made'] == r['python']
        assert c.post('/runtime/create', json={'root': str(karma)}).json()['note'] == '', 'a venv that is there is not news'
        assert c.post('/runtime/create', json={'root': str(tmp_path)}).status_code >= 400, 'never outside the open folders'

@pytest.mark.no_venv
def test_a_chosen_interpreter_runs_everything_with_nothing_made(tmp_path, monkeypatch):
    "The person's choice for a project is the other way to answer the notice."
    from leela.blocks.debug.debug import DebugSession
    orgs, karma, shared = _orgs(tmp_path)
    made, seen, got = _made(monkeypatch), [], {}
    monkeypatch.setattr(DebugSession, 'start_adapter', lambda self: seen.append(self.python))
    monkeypatch.setattr(DebugSession, 'launch', lambda self, config, breakpoints: None)
    (karma/'main.py').write_text('print(1)\n')
    ws = Workspace(roots=[orgs]); ws.open(str(karma/'main.py'))
    ws.choose_python(str(shared))
    async def start(cmd, **kw): got.update(kw)
    ws.dev.start = start
    async def get(key, **kw): got['kernel'] = kw['python']
    ws.pool.get = get
    asyncio.run(ws.run(str(karma/'main.py'))); asyncio.run(ws.kernel())
    with TestClient(ide_app(ws)) as c: c.post('/debug/start', json={'program': str(karma/'main.py'), 'cwd': str(karma)})
    assert made == [] and got['python'] == got['kernel'] == seen[0] == str(shared)

def test_choosing_leelas_own_python_stores_the_python_it_runs_on(tmp_path):
    "In the bundle `sys.executable` is the app, and a kernel started on it starts the app again."
    import sys
    from leela.blocks.runtime.kernels import runtime_python
    ws = Workspace(roots=[tmp_path]); ws.open(str(_cell_nb(tmp_path/'a.ipynb')))
    proj = ws.choose_python(sys.executable)
    assert ws.chosen_python[proj] == runtime_python()

@pytest.mark.no_venv
def test_the_agent_is_told_the_two_choices_and_makes_nothing(tmp_path, monkeypatch):
    "The agent's first run_python made the project's venv, or ran on Leela's own Python."
    orgs, karma, shared = _orgs(tmp_path)
    nb = _cell_nb(karma/'nbs'/'a.ipynb')
    made = _made(monkeypatch)
    ws = Workspace(roots=[orgs], approvals='auto'); ws.open(str(nb))
    with TestClient(ide_app(ws)):
        host = ws.inline_ai.host
        with pytest.raises(RuntimeError, match=r'No Python environment for karma\..*Set up \.venv or Choose interpreter.*Ask them; do not make a venv'):
            host.run_python('1')
        assert 'Ask them; do not make a venv' in host.nb_run_cell(str(nb), 'c0')
    assert made == [] and not (karma/'.venv').exists()

@pytest.mark.slow
@pytest.mark.makes_venv
@pytest.mark.no_venv
@pytest.mark.skipif(not shutil.which('uv'), reason='needs uv to create an environment')
def test_a_venv_set_up_runs_the_notebook_on_leelas_minor_without_leelas_packages(tmp_path):
    "The real thing: Set up .venv has uv make karma/.venv on Leela's Python minor, and the notebook's kernel imports only what is in it."
    import sys
    from leela.blocks.runtime.kernels import NoVenv
    orgs, karma, shared = _orgs(tmp_path)
    ws = Workspace(roots=[orgs], port=8461)
    async def go():
        await ws.opened()
        tab = ws.open(str(karma/'nbs'/'a.ipynb'))
        with pytest.raises(NoVenv): await ws.kernel(tab)
        assert not (karma/'.venv').exists()
        await asyncio.to_thread(ws.setup_venv, karma)
        k = await ws.kernel(tab)
        r = await k.execute('import sys; print(sys.prefix, sys.version_info[:2])')
        assert str(karma/'.venv') in r.text and str(tuple(sys.version_info[:2])) in r.text, r.text
        for name in ('leela', 'rupaka', 'ramabana'):
            r = await k.execute(f'import {name}')
            assert not r.ok and 'No module named' in (r.text + str(r.error)), f'{name} imported in the project kernel: borrowed'
        await ws.shutdown()
    asyncio.run(go())

def _checkout(orgs, name, py=True):
    "A git checkout in `orgs` with no venv: a Python project when `py`."
    import subprocess
    d = orgs/name; d.mkdir(parents=True)
    subprocess.run(['git', 'init', '-q', str(d)], check=True)
    if py: (d/'pyproject.toml').write_text('')
    (d/'main.py').write_text('print(1)\n')
    return d

def _made(monkeypatch):
    "Record each project `make_venv` is asked for, and make a stand-in venv there."
    import kunda.support as ks
    made = []
    def fake(root, python=None): made.append(Path(root)); return str(_venv(Path(root)))
    monkeypatch.setattr(ks, 'make_venv', fake)
    return made

def test_each_workspace_pool_asks_the_os_for_its_inspector_port():
    "Pools took 8400, 8500, ... so each kernel's inspector sat on a fixed port a person may want."
    from itertools import islice
    from leela.app import _pool_ports
    assert list(islice(_pool_ports(), 3)) == [0, 0, 0]
    assert list(islice(_pool_ports(8400), 2)) == [8400, 8500], 'an explicit --kernel-port keeps its ladder'
    assert Workspace().pool.port == 0

def _first_free(start=8000):
    import socket
    for p in range(start, start+50):
        with socket.socket() as s:
            try: s.bind(('127.0.0.1', p)); return p
            except OSError: continue

@pytest.mark.slow
def test_a_server_on_8000_still_starts_while_a_kernel_runs(tmp_path):
    "The inspector took the first free port from 8000, so a person's own server there failed to bind."
    import socket
    want, ws = _first_free(), Workspace(roots=[tmp_path])
    async def go():
        k = await ws.pool.get('p1', cwd=str(tmp_path))
        try:
            assert k.base, k.boot_error
            with socket.socket() as s: s.bind(('127.0.0.1', want)); s.listen()
            return int(k.base.rsplit(':', 1)[-1])
        finally: await ws.pool.close_all()
    assert asyncio.run(go()) != want
