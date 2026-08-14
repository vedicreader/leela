"""Tests for run configurations, and for what the variable panel is allowed to watch.

The question behind all of this was: *if I start uvicorn myself, does the panel pick it
up?* The answer is no, and it is not a bug -- there is no inspector in that process, so
there is nothing to read. What these cover is the two ways to make the answer yes: a run
configuration, where leela starts the command with an inspector inside it, and the env
picker, which lets the panel look at any process that registered one.
"""

import json
import os
import sys

import pytest
from fastcore.all import Path

from leela.blocks.runtime.devserver import DevServer, DevServers, infer_watch, run_command, split_cmd
from leela.blocks.runs.runs import RUNS_FILE, Run, Runs
from leela.workspace import _EnvClient


# ---- the configurations ----------------------------------------------------
def test_run_environment_file_is_confined_and_overlaid_by_explicit_values(tmp_path):
    (tmp_path/'.env.local').write_text('TOKEN="from file"\nPORT=8000\nexport DEBUG=true\n')
    run = Run('api', 'python app.py', env={'PORT': '9000'}, env_file='.env.local')
    assert run.resolved_env(tmp_path) == {'TOKEN': 'from file', 'PORT': '9000', 'DEBUG': 'true'}
    run.env_file = '../outside.env'
    with pytest.raises(ValueError, match='outside the project'):
        run.resolved_env(tmp_path)


def test_a_configuration_round_trips_through_the_project(tmp_path):
    "They live in the project, next to the code they run, so the next person finds them."
    r = Runs(tmp_path)
    assert r.runs == [] and str(r.path).endswith(RUNS_FILE)
    r.add(Run(name='api', cmd='uvicorn app:app --port 8000', watch='app'))
    assert (tmp_path/RUNS_FILE).exists()
    again = Runs(tmp_path)
    assert [x.name for x in again.runs] == ['api']
    assert again.get('api').cmd == 'uvicorn app:app --port 8000'
    again.remove('api')
    assert Runs(tmp_path).runs == []


def test_a_broken_configurations_file_is_a_note_not_a_crash(tmp_path):
    "A typo in a project file must not stop the IDE opening the project."
    (tmp_path/'.leela').mkdir()
    (tmp_path/RUNS_FILE).write_text('{"runs": [oops]}')
    r = Runs(tmp_path)
    assert r.runs == [] and str(tmp_path) in r.note


def test_a_bad_entry_costs_that_entry(tmp_path):
    (tmp_path/'.leela').mkdir()
    (tmp_path/RUNS_FILE).write_text(json.dumps({'runs': [
        {'name': 'good', 'cmd': 'python x.py'}, {'nope': 1}]}))
    r = Runs(tmp_path)
    assert [x.name for x in r.runs] == ['good'] and r.note


def test_an_open_file_always_gives_the_picker_something_to_offer(tmp_path):
    "A picker whose only content is 'you have none' teaches nobody what the feature is."
    r = Runs(tmp_path)
    got = r.for_file(tmp_path/'train.py')
    assert got.name == 'train' and got.cmd.endswith('train.py') and got.watch == 'train'
    assert r.runs == [], 'an inferred configuration is offered, not saved'


# ---- resolving a command ---------------------------------------------------
def test_a_command_line_is_split_like_a_shell():
    assert split_cmd('uvicorn app:app --port 8000') == ['uvicorn', 'app:app', '--port', '8000']
    assert split_cmd(['python', '-m', 'x']) == ['python', '-m', 'x']


def test_the_watched_module_is_inferred_from_the_command():
    """`uvicorn app:app` is about `app`, not about uvicorn.

    Which module the panel should show is the one question a run configuration cannot
    guess wrong quietly -- watch the wrong namespace and the panel is simply empty.
    """
    assert infer_watch(['uvicorn', 'app:app', '--port', '8000']) == 'app'
    assert infer_watch(['gunicorn', '-w', '4', 'server:application']) == 'server'
    assert infer_watch(['python', 'train.py']) == 'train'
    assert infer_watch(['pytest', '-x']) == ''


def test_the_child_command_carries_the_watch_and_the_argv(tmp_path):
    s = DevServer(script='uvicorn api:app --port 8123', cwd=str(tmp_path), port=9100)
    cmd = s._cmd()
    assert cmd[:4] == [sys.executable, '-u', '-m', 'leela.blocks.runtime.devserver']
    assert '--watch' in cmd and cmd[cmd.index('--watch') + 1] == 'api'
    assert cmd[cmd.index('--') + 1:] == ['uvicorn', 'api:app', '--port', '8123']
    assert not s.is_script and s.label == 'uvicorn api:app'


def test_a_plain_script_still_runs_the_way_it_always_did(tmp_path):
    p = tmp_path/'app.py'
    p.write_text('x = 1\n')
    s = DevServer(script=str(p), port=9100)
    assert s.is_script and s.label == 'app'
    assert s._cmd()[-1] == str(p)
    assert s._cwd() == str(tmp_path)


def test_two_commands_are_two_servers_but_one_script_is_one():
    "A path is resolved so the same file opened two ways is one server; a command line is itself."
    assert DevServers.key('uvicorn app:app --port 8000') != DevServers.key('uvicorn app:app --port 8001')
    assert DevServers.key('./x.py') == DevServers.key(str(Path('x.py').resolve()))


def test_a_command_runs_in_this_process(tmp_path, monkeypatch, capsys):
    """The whole point: the command runs *here*, where the inspector is.

    A subprocess would be simpler and would put the namespace somewhere the panel cannot
    reach, which is the difference between this and typing the same line in a terminal.
    """
    p = tmp_path/'job.py'
    p.write_text("import sys; print('ran', sys.argv[1:])\n")
    monkeypatch.chdir(tmp_path)
    run_command(['python', str(p), '--flag'])
    assert "ran ['--flag']" in capsys.readouterr().out


def test_a_module_runs_with_runpy(tmp_path, monkeypatch, capsys):
    (tmp_path/'mymod.py').write_text("print('module ran')\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    run_command(['python', '-m', 'mymod'])
    assert 'module ran' in capsys.readouterr().out


def test_an_unresolvable_command_says_so_rather_than_forking():
    "Silently running it in a subprocess would look like the feature working and show nothing."
    with pytest.raises(SystemExit) as e: run_command(['definitely-not-installed', '--x'])
    assert 'cannot run' in str(e.value)


# ---- what the panel may watch ----------------------------------------------
def test_the_env_list_covers_kernels_and_anything_that_registered(ws, monkeypatch):
    "A notebook kernel, an app leela started, and a process that called serve() are all envs."
    # `leela.core.inspectors` is where the registry is read; dhrishti owns the format, and
    # `tests/test_inspectors.py` is what keeps the two agreeing.
    monkeypatch.setattr('leela.core.inspectors.active',
                        lambda: [{'name': 'api', 'base': 'http://127.0.0.1:9500', 'pid': 4321,
                                  'cwd': '/tmp'}])
    ws.pool.kernels['k'] = type('K', (), {'base': 'http://127.0.0.1:8000', 'pid': 11})()
    envs = ws.envs()
    assert {e['kind'] for e in envs} == {'kernel', 'app'}
    assert [e['name'] for e in envs if e['kind'] == 'app'] == ['api']


def test_watching_an_env_points_the_panel_at_it_and_back(ws, monkeypatch):
    monkeypatch.setattr('leela.core.inspectors.active',
                        lambda: [{'name': 'api', 'base': 'http://127.0.0.1:9500', 'pid': 4321}])
    ws.watch_env('http://127.0.0.1:9500')
    assert isinstance(ws.inspector(), _EnvClient)
    ws.watch_env(None)
    assert not isinstance(ws.inspector(), _EnvClient)


def test_watching_an_env_that_died_falls_back_rather_than_going_blank(ws, monkeypatch):
    "An app you were watching exits; the panel should quietly return to the kernel."
    monkeypatch.setattr('leela.core.inspectors.active', lambda: [])
    ws.watch_env('http://127.0.0.1:9999')
    assert not isinstance(ws.inspector(), _EnvClient)
    assert ws.env_base is None


def test_a_watched_env_executes_through_its_owner_inspector(monkeypatch):
    """A picked runtime has no shell channel, but its inspector owns the live namespace."""
    import asyncio
    e = _EnvClient('http://127.0.0.1:9500', 'api')
    async def answer(path, params=None, timeout=15):
        assert path == '/api/exec' and params == {'code': '1+1', 'scope': 'global'}
        return {'ok': True, 'stdout': '', 'error': None,
                'result': {'name': 'result', 'type': 'int', 'value': '2'}}
    monkeypatch.setattr(e, 'api', answer)
    r = asyncio.run(e.execute('1+1'))
    assert r.ok and r.outputs[0]['data']['text/plain'] == '2'
