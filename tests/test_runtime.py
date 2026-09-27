"Runtimes: project kernels, tab bindings, run configurations, the debugger."

import json
import os
import shutil
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
import pytest
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.blocks.runtime.kernels import nearest_python, project_python
from leela.workspace import Workspace
from tests.assets import JS, read
import asyncio
import sys
from fastcore.all import Path, first
from leela.blocks.runtime import devserver
from leela.blocks.runtime.devserver import DevServer, DevServers, infer_watch, run_command, split_cmd
from leela.blocks.runs.runs import RUNS_FILE, Run, Runs
from leela.workspace import _EnvClient
from leela.blocks.runtime.kernels import find_pythons, run_file_src
from leela.blocks.debug.debug import DebugSession, debugpy_available
import subprocess
from kunda import support as support
import numpy as np
import pandas as pd
from dhrishti.core import PROFILES, SORTS, expand, grid_page, value_str, var_info
from dhrishti.runtime import Bridge, NsClient, set_logging
from dhrishti.agent import AgentSession
import dhrishti.serving as ds

def _client(root):
    ws = Workspace(roots=[root])
    return TestClient(ide_app(ws)), ws

def test_a_folder_without_an_environment_says_so_and_says_uv_can_fix_it(tmp_path):
    (tmp_path/'main.py').write_text('print(1)')
    client, ws = _client(tmp_path)
    with client as c: d = c.get('/runtime/info').json()
    assert d['needs_create'] is True and d['python'] == ''
    assert d['uv'] is bool(shutil.which('uv')), 'the client decides whether to ask by this'
    assert ws.pool.default_python is None, 'nothing chosen yet, which is the bug being avoided'

def test_an_existing_venv_is_adopted_and_needs_no_creating(tmp_path):
    py = tmp_path/'.venv'/'bin'/'python'
    py.parent.mkdir(parents=True)
    py.write_text('#!/bin/sh\nexit 1\n'); py.chmod(0o755)
    client, ws = _client(tmp_path)
    with client as c: d = c.get('/runtime/info').json()
    assert d['needs_create'] is False
    assert d['python'] == str(py) and ws.pool.default_python == str(py)


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
    assert ws.pool.default_python == made, 'and the pool switched to it, not PATH'
    assert after['needs_create'] is False

@pytest.mark.skipif(not shutil.which('uv'), reason='needs uv to create an environment')
def test_creating_twice_refuses_rather_than_overwriting(tmp_path):
    "An existing .venv is someone's environment. Refuse, do not rebuild it."
    (tmp_path/'.venv').mkdir()
    client, _ = _client(tmp_path)
    with client as c: r = c.post('/runtime/create')
    assert r.status_code == 400
    assert 'already exists' in r.json()['error']

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
    assert ws.pool.default_python == str(pa), 'precondition: the pool holds the first root'
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

def test_a_terminal_outside_any_checkout_still_gets_the_workspace_environment(tmp_path):
    from leela.app import _term_python
    root = tmp_path/'repo'; py = _venv(root)
    elsewhere = tmp_path/'scratch'; elsewhere.mkdir()
    ws = Workspace(roots=[root])
    assert _term_python(ws, elsewhere) == str(py)

def test_the_environment_of_a_project_is_what_uv_and_a_console_script_read(tmp_path):
    "One builder for every child Leela spawns, so a release step and a shell agree."
    from leela.blocks.runtime.kernels import venv_env
    py = _venv(tmp_path)
    env = venv_env(str(py), {'PATH': '/usr/bin', 'PYTHONHOME': '/somewhere/else',
                             'UV_PROJECT_ENVIRONMENT': '/somewhere/else/.venv'})
    assert env['VIRTUAL_ENV'] == str(tmp_path/'.venv')
    # It applies wherever the process ends up, not where it started: a `uv sync` run in another
    # checkout syncs that project's lock into this venv and prunes whatever the lock omits.
    assert 'UV_PROJECT_ENVIRONMENT' not in env, 'a venv this one does not own is not ours to name'
    assert env['PATH'].split(os.pathsep)[0] == str(py.parent), 'the venv resolves console scripts first'
    assert 'PYTHONHOME' not in env, 'inherited from a frozen app, it would override the venv'
    assert venv_env(None, {'PATH': '/usr/bin'}) == {'PATH': '/usr/bin'}, 'nothing found, nothing claimed'

def test_a_release_runs_in_the_venv_of_the_project_being_released(tmp_path):
    "The reported failure: `nbdev_prepare` from a system Python 3.8."
    from leela.blocks.pipelines.pipelines import Release
    from leela.blocks.runtime.kernels import python_for
    a, b = tmp_path/'repo-a', tmp_path/'repo-b'
    pa, pb = _venv(a), _venv(b)
    ws = Workspace(roots=[a, b])
    assert ws.pool.default_python == str(pa), 'precondition: the pool holds the first root'
    assert python_for(b, ws) == str(pb), 'a release of repo-b belongs in repo-b'
    p = Release(b, python=python_for(b, ws))
    env = p._env()
    assert env['PATH'].split(os.pathsep)[0] == str(pb.parent)
    assert env['VIRTUAL_ENV'] == str(b/'.venv')

def test_every_pipeline_resolves_its_interpreter_from_the_project(tmp_path):
    "Release, deploy and drive are one pipeline with three plans; none may key off the first root."
    from leela.blocks.drive import app as drive_app
    from leela.blocks.pipelines import app as pipe_app
    for mod in (pipe_app, drive_app):
        src = Path(mod.__file__).read_text(encoding='utf-8')
        assert 'python_for(root, ctx.session)' in src, mod.__name__
        assert 'ctx.session.pool.default_python' not in src, f'{mod.__name__} still keys off the first root'


def test_git_itself_runs_with_the_checkouts_environment(tmp_path):
    "A hook is a console script of the repository being committed to, not of Leela."
    from leela.blocks.git.git import wire_env
    g = wire_env()
    root = tmp_path/'proj'; py = _venv(root); (root/'.git').mkdir()
    env = g.env(root/'sub'/'deeper')
    assert env['PATH'].split(os.pathsep)[0] == str(py.parent), 'found by searching upwards'
    bare = tmp_path/'bare'; (bare/'.git').mkdir(parents=True)
    assert g.env(bare) is None, 'no venv, nothing claimed -- git inherits what Leela has'
    assert g.resolves(root/'sub', 'definitely-not-installed-anywhere') == ''

def test_find_repos_searches_deeper_than_discover_and_filters_by_name(tmp_path):
    "`discover` is one level deep by design; finding a checkout you half-remember is not."
    from leela.blocks.git.repos import find_repos
    for rel in ('work/alpha-service', 'work/beta-service', 'play/deep/gamma-tool'):
        (tmp_path/rel/'.git').mkdir(parents=True)
        (tmp_path/rel/'.git'/'HEAD').write_text('ref: refs/heads/main\n')
    (tmp_path/'work'/'not-a-repo').mkdir(parents=True)
    names = {p.name for p in find_repos(tmp_path)}
    assert names == {'alpha-service', 'beta-service', 'gamma-tool'}, 'three levels down, and no plain folder'
    assert {p.name for p in find_repos(tmp_path, 'service')} == {'alpha-service', 'beta-service'}
    assert {p.name for p in find_repos(tmp_path, 'gamma')} == {'gamma-tool'}

def test_find_repos_matches_a_linked_worktree_whose_git_is_a_file(tmp_path):
    "A worktree's `.git` is a file pointing at the real one. It is still somewhere to open."
    from leela.blocks.git.repos import find_repos
    wt = tmp_path/'checkouts'/'feature-branch'
    wt.mkdir(parents=True)
    (wt/'.git').write_text('gitdir: /elsewhere/.git/worktrees/feature-branch\n')
    assert [p.name for p in find_repos(tmp_path)] == ['feature-branch']

def test_the_finder_route_answers_for_a_folder_not_yet_open(tmp_path):
    "The dialog searches a directory you have not opened, which is why it takes a base."
    (tmp_path/'elsewhere'/'zeta-app'/'.git').mkdir(parents=True)
    (tmp_path/'elsewhere'/'zeta-app'/'.git'/'HEAD').write_text('ref: refs/heads/main\n')
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as c:
        d = c.get(f'/git/find?base={tmp_path}&q=zeta').json()
    assert [r['name'] for r in d['repos']] == ['zeta-app']
    assert d['repos'][0]['path'].endswith('elsewhere/zeta-app')

def test_finding_a_repository_is_reachable_from_any_panel():
    "Browsing is `o` in the files panel; this is the other way in and must be global."
    from leela.core.keys import KEYS, chord_display
    find = [k for k in KEYS if k.action == 'find_repo']
    assert len(find) == 1 and find[0].scope == 'global'
    assert chord_display('find_repo') and 'o' in chord_display('find_repo')
    assert [k.scope for k in KEYS if k.action == 'add_root'] == ['files'], 'browsing stays where it was'

def test_the_runtime_list_is_asked_of_ramabana_not_duplicated(tmp_path):
    "leela's copy of the runtime list drifted twice."
    from leela.blocks.agent.models import runtimes
    from leela.agent.core import RUNTIME_NAMES, runtime_available
    got = {r['value']: r['available'] for r in runtimes()}
    assert tuple(got) == RUNTIME_NAMES, 'exactly what register_model accepts, in its order'
    for name, avail in got.items():
        assert avail is bool(runtime_available(name)), f'{name} must report what rishi says'
    assert got['remote'] is True

def test_the_model_dialog_is_told_which_runtimes_exist(tmp_path):
    from leela.agent.core import RUNTIME_NAMES
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as c: d = c.get('/agent/models').json()
    assert [r['value'] for r in d['runtimes']] == list(RUNTIME_NAMES)
    # The remedy moved to the server with the label: `pip install rishi[cursor]` is not how you
    # get the Cursor agent, and the browser had no way to know that.
    why = {r['value']: r['why'] for r in d['runtimes']}
    assert 'rishi[mlx]' in why['mlx'], 'saying what to install for the ones that are missing'
    assert 'Claude Code' in why['claude'] and 'pip install' not in why['claude'], \
        'a harness runtime is not a pip extra, and rishi ships the SDK itself'
    assert 'cursor' not in why, 'and Cursor is no longer offered at all'

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

def test_an_accelerator_leela_cannot_offer_is_refused_before_it_reaches_an_engine(tmp_path):
    "Validated even with no assistant built, or it would be stored to fail at the first request."
    ws = Workspace(roots=[tmp_path]); ws._state_path = tmp_path/'ws.json'
    with TestClient(ide_app(ws)) as c:
        r = c.post('/agent/settings', json={'litert_backend': 'tpu'})
    assert r.status_code == 400 and 'cpu, gpu' in r.json()['error']
    assert ws.litert_backend != 'tpu'


def test_the_finder_skips_the_directories_that_made_it_slow(tmp_path):
    "Object stores, virtualenvs and caches never hold a checkout worth opening."
    from leela.blocks.git.repos import find_repos
    good = tmp_path/'work'/'real-repo'
    (good/'.git').mkdir(parents=True); (good/'.git'/'HEAD').write_text('ref: x')
    for junk in ('node_modules/vendored', '.venv/src/pkg', '.cache/thing'):
        d = tmp_path/junk
        (d/'.git').mkdir(parents=True); (d/'.git'/'HEAD').write_text('ref: x')
    assert [p.name for p in find_repos(tmp_path)] == ['real-repo']

def test_a_terminal_is_a_login_shell_in_the_projects_environment():
    from leela.blocks.term.term import default_shell, shell_argv
    block = JS[JS.index('async function gitDo('):]
    block = block[:block.index('\nfunction gitOperationBanner')]
    block = JS[JS.index('async function pollRunLogs'):]
    block = block[:block.index('function leeDock')]
    assert shell_argv('/opt/homebrew/bin/fish') == ['/opt/homebrew/bin/fish', '-l']
    assert shell_argv('/bin/bash', login=False) == ['/bin/bash']
    assert shell_argv('/bin/bash', ['-i', '-c', 'true']) == ['/bin/bash', '-i', '-c', 'true']
    assert shell_argv('', (), True) == [default_shell(), '-l'], 'empty means $SHELL'
    block = JS[JS.index('async function leeExternalTerm'):JS.index('function leeNewTerm')]


def test_a_half_typed_path_browses_what_exists_and_returns_the_rest(tmp_path):
    "The normal state of a box you are completing in is a path that does not exist yet."
    (tmp_path/'personal').mkdir(); (tmp_path/'.hidden').mkdir()
    client, _ = _client(tmp_path)
    with client as c:
        d = c.get('/fs/browse', params={'path': str(tmp_path/'per')}).json()
        assert d['path'] == str(tmp_path) and d['partial'] == 'per'
        assert 'personal' in [x['name'] for x in d['dirs']]
        assert '.hidden' not in [x['name'] for x in d['dirs']], 'hidden folders stay out of the way'
        asked = c.get('/fs/browse', params={'path': str(tmp_path/'.hid')}).json()
        assert '.hidden' in [x['name'] for x in asked['dirs']], 'until they are asked for by name'

def test_the_picker_starts_where_your_projects_are_rather_than_at_home(tmp_path, monkeypatch):
    "Home is a long list of things that are not projects, so `o` opened onto the wrong list."
    from leela.blocks.settings import settings as S
    (code := tmp_path/'code').mkdir(); (mine := tmp_path/'elsewhere').mkdir()
    monkeypatch.setattr(S, 'CODE_FOLDER', str(code))
    monkeypatch.setattr(S, 'user_settings_file', lambda: tmp_path/'settings.json')
    client, _ = _client(tmp_path)
    with client as c:
        assert c.get('/fs/browse', params={'path': ''}).json()['path'] == str(code)
        c.post('/settings/save', json={'scope': 'user', 'section': 'workbench',
                                       'values': {'projectFolder': str(mine)}})
        assert c.get('/fs/browse', params={'path': ''}).json()['path'] == str(mine), 'and a setting wins'

def test_a_start_folder_that_is_not_there_falls_back_rather_than_failing(tmp_path, monkeypatch):
    from leela.blocks.settings.settings import start_folder
    from leela.blocks.settings import settings as S
    monkeypatch.setattr(S, 'CODE_FOLDER', str(tmp_path/'no-such-folder'))
    monkeypatch.setattr(S, 'user_settings_file', lambda: tmp_path/'settings.json')
    assert start_folder() == Path.home()


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
    assert path_prelude('/p/.venv/bin/python', '/opt/homebrew/bin/fish') == \
        ' set -gx PATH /p/.venv/bin $PATH'
    assert path_prelude('/p/.venv/bin/python', '/bin/bash') == ' export PATH="/p/.venv/bin:$PATH"'
    assert path_prelude('/p/.venv/bin/python', '/bin/zsh') == ' export PATH="/p/.venv/bin:$PATH"'
    assert path_prelude('/p/.venv/bin/python', '/bin/tcsh') == ' setenv PATH "/p/.venv/bin:$PATH"'
    assert path_prelude('', '/bin/bash') == '', 'no interpreter, nothing to prepend'
    for shell in ('/bin/bash', '/opt/homebrew/bin/fish'):
        assert path_prelude('/p/.venv/bin/python', shell).startswith(' '), 'kept out of history'

def test_terminals_report_the_key_each_pty_is_filed_under(tmp_path):
    "The browser picks terminal ids, so it has to know which are taken."
    import asyncio
    from leela.blocks.term.term import Terminals
    async def run():
        "On a loop: a pty's ring wakes its readers on the one that was running when it was opened."
        terms = Terminals(cwd=tmp_path)
        terms.open('term-1', argv=['/bin/sh', '-c', 'sleep 30'])
        try: return terms, terms.states()
        finally: terms.close_all()
    terms, states = asyncio.run(run())
    assert [s['id'] for s in states] == ['term-1']
    assert states[0]['alive'] is True and states[0]['pid']
    assert terms.states() == [], 'and closing takes the process with it'


def test_an_external_terminal_is_offered_only_when_one_is_installed(tmp_path, monkeypatch):
    "xterm.js cannot be attached to a running terminal, so the honest offer is to launch one."
    from leela.blocks.term import term as T
    assert T.external_terminal_argv(tmp_path, 'kaku {dir}') == ['kaku', str(tmp_path)]
    assert T.external_terminal_argv(tmp_path, 'kaku') == ['kaku', str(tmp_path)]
    assert T.external_terminal_argv(tmp_path, 'wezterm start --cwd {dir}') == \
        ['wezterm', 'start', '--cwd', str(tmp_path)]
    monkeypatch.setattr(T.shutil, 'which', lambda n: None)
    monkeypatch.setattr(T, 'EXTERNAL_TERMINALS', (('NoSuchTerminal', 'no-such-terminal'),))
    assert T.external_terminal_argv(tmp_path) is None, 'no terminal, no button'


def test_a_terminal_says_which_checkout_it_belongs_to(tmp_path):
    """A shell is one process in one directory and cannot follow the project by itself, so the client keeps one per checkout."""
    import subprocess
    orgs = tmp_path/'orgs'
    a, b = orgs/'repo-a', orgs/'repo-b'
    for d in (a, b):
        (d/'src').mkdir(parents=True)
        subprocess.run(['git', 'init', '-q', str(d)], check=True)
        (d/'src'/'main.py').write_text('x = 1\n')
    ws = Workspace(roots=[orgs])
    with TestClient(ide_app(ws)) as c:
        assert c.get('/term/info').json()['project'] == str(orgs), 'nothing open, so the open folder'
        ws.open(a/'src'/'main.py')
        first = c.get('/term/info').json()
        assert first['project'] == str(a), 'the checkout the open file is in'
        ws.open(b/'src'/'main.py')
        assert c.get('/term/info').json()['project'] == str(b), 'and it follows the file'
        from leela.blocks.term.app import term_project
        assert term_project(ws, a/'src') == str(a), 'a directory inside the checkout is in it'
        assert term_project(ws, None) == ''

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

def test_the_picker_lists_a_venv_deeper_than_the_scan_reaches(tmp_path):
    "Two levels down is past the scan, so the interpreter in use is listed because it is in use."
    root = tmp_path/'code'; root.mkdir()
    p = _venv(root/'org'/'repo')
    (root/'org'/'repo'/'nb.ipynb').write_text('{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}')
    ws = Workspace(roots=[root])
    opts = ws.kernel_options(ws.open(root/'org'/'repo'/'nb.ipynb'))
    assert [x['path'] for x in opts['pythons'] if x['current']] == [str(p)]

def test_a_notebook_gets_its_own_project_venv_not_the_last_one_chosen(tmp_path):
    "The reported failure: opening a notebook under `nbs/` ran it in another checkout's venv."
    from leela.blocks.runtime.kernels import python_for
    a, b = tmp_path/'repo-a', tmp_path/'repo-b'
    pa, pb = _venv(a), _venv(b)
    (b/'nbs').mkdir(parents=True)
    (b/'nbs'/'00_core.ipynb').write_text('{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}')
    ws = Workspace(roots=[a, b])
    assert ws.pool.default_python == str(pa), 'precondition: the pool holds the first root'
    tab = ws.open(b/'nbs'/'00_core.ipynb')
    assert tab.kind == 'notebook' and Path(ws.cwd_for(tab)) == b/'nbs', 'a notebook runs beside itself'
    assert python_for(ws.cwd_for(tab), ws) == str(pb), 'the notebook belongs to repo-b'

def test_the_walk_up_stops_at_the_open_folder(tmp_path):
    "A venv above the workspace belongs to something else; adopting it is worse than finding none."
    outer = tmp_path/'outer'
    _venv(outer)
    inner = outer/'project'/'nbs'
    inner.mkdir(parents=True)
    assert nearest_python(inner) == str(outer/'.venv'/'bin'/'python'), 'unbounded, it climbs'
    assert nearest_python(inner, stop=outer/'project') is None, 'bounded, it does not'

def test_a_venv_in_the_notebooks_own_folder_still_wins(tmp_path):
    "Nearest means nearest: the walk starts where it always did."
    root = tmp_path/'repo'
    outer, inner = _venv(root), _venv(root/'nbs')
    assert nearest_python(root/'nbs', stop=root) == str(inner) != str(outer)

def _notebook(path):
    path.write_text('{"nbformat":4,"nbformat_minor":5,"metadata":{},"cells":[]}')

def test_each_notebook_has_a_distinct_kernel_key(tmp_path):
    a, b = tmp_path/'a.ipynb', tmp_path/'b.ipynb'
    _notebook(a); _notebook(b)
    ws = Workspace(roots=[tmp_path])
    ta = ws.open(a); tb = ws.open(b)
    assert ta.private_kernel and tb.private_kernel
    assert ws.kernel_key(ta) == f'tab:{a}'
    assert ws.kernel_key(tb) == f'tab:{b}'
    assert ws.kernel_key(ta) != ws.kernel_key(tb)

def test_source_files_share_the_folder_kernel(tmp_path):
    a, b = tmp_path/'a.py', tmp_path/'b.py'
    a.write_text('a = 1\n'); b.write_text('b = 2\n')
    ws = Workspace(roots=[tmp_path])
    ta = ws.open(a); tb = ws.open(b)
    assert not ta.private_kernel and not tb.private_kernel
    assert ws.kernel_key(ta) == ws.kernel_key(tb) == str(tmp_path)

def test_a_notebook_can_explicitly_attach_to_the_folder_kernel(tmp_path):
    p = tmp_path/'analysis.ipynb'; _notebook(p)
    ws = Workspace(roots=[tmp_path]); tab = ws.open(p)
    tab.private_kernel = False
    assert ws.kernel_key(tab) == str(tmp_path)

def test_notebook_kernel_cwd_is_the_notebook_directory(tmp_path):
    one, two = tmp_path/'one', tmp_path/'two'
    one.mkdir(); two.mkdir(); nbs = two/'nbs'; nbs.mkdir()
    p = nbs/'analysis.ipynb'; _notebook(p)
    ws = Workspace(roots=[one, two]); tab = ws.open(p)
    assert ws.cwd_for(tab) == nbs
    seen = {}
    async def get(key, **kwargs): seen.update(key=key, **kwargs); return object()
    ws.pool.get = get
    asyncio.run(ws.kernel(tab))
    assert seen['cwd'] == nbs and seen['name'] == 'two'

def test_notebooks_choose_their_own_project_venv(tmp_path):
    a, b = tmp_path/'ramabana', tmp_path/'rishi'
    a.mkdir(); b.mkdir(); pa, pb = a/'.venv'/'bin'/'python', b/'.venv'/'bin'/'python'
    pa.parent.mkdir(parents=True); pb.parent.mkdir(parents=True); pa.touch(); pb.touch()
    na, nb = a/'a.ipynb', b/'b.ipynb'; _notebook(na); _notebook(nb)
    ws = Workspace(roots=[a, b]); ta, tb = ws.open(na), ws.open(nb); seen = []
    async def get(key, **kwargs): seen.append((key, kwargs['python'])); return object()
    ws.pool.get = get
    asyncio.run(ws.kernel(ta)); asyncio.run(ws.kernel(tb))
    assert seen == [(f'tab:{na}', str(pa)), (f'tab:{nb}', str(pb))]

def test_notebook_parent_paths_match_jupyter_and_pycharm(tmp_path):
    project = tmp_path/'project'; nbs = project/'nbs'; nbs.mkdir(parents=True)
    p = nbs/'analysis.ipynb'; _notebook(p)
    ws = Workspace(roots=[project]); tab = ws.open(p)
    assert (ws.cwd_for(tab)/'..').resolve() == project.resolve()

def test_existing_notebook_kernel_moves_to_corrected_cwd_without_losing_namespace(tmp_path):
    project = tmp_path/'project'; nbs = project/'nbs'; nbs.mkdir(parents=True)
    p = nbs/'analysis.ipynb'; _notebook(p)
    ws = Workspace(roots=[project]); tab = ws.open(p)
    calls = []
    class Result:
        ok=True; error=''
    class Existing:
        cwd=project
        async def execute(self, code): calls.append(code); return Result()
    kernel=Existing()
    async def get(key, **kwargs): return kernel
    ws.pool.get=get
    assert asyncio.run(ws.runtime(tab)) is kernel
    assert kernel.cwd == nbs and calls and 'chdir' in calls[0]

def test_private_notebook_can_override_cwd_inside_an_open_folder(tmp_path):
    sub = tmp_path/'nbs'; sub.mkdir()
    p = tmp_path/'analysis.ipynb'; _notebook(p)
    ws = Workspace(roots=[tmp_path]); tab = ws.open(p)
    tab.cwd = str(sub)
    assert ws.cwd_for(tab) == sub

def test_workspace_state_persists_an_explicit_attachment_without_running_state(tmp_path):
    p = tmp_path/'analysis.ipynb'; _notebook(p)
    ws = Workspace(roots=[tmp_path]); tab = ws.open(p)
    tab.private_kernel = False; tab.running = 2
    state = ws.state()
    assert state['version'] == 2
    assert state['tabs'][0]['private_kernel'] is False
    assert 'running' not in state['tabs'][0]

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
    with pytest.raises(SystemExit) as e: run_command(['definitely-not-installed', '--x'])
    assert 'cannot run' in str(e.value)


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


def test_a_command_runs_in_this_process(tmp_path, monkeypatch, capsys):
    "The whole point: the command runs *here*, where the inspector is."
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


def test_a_failed_dev_command_prints_its_system_exit(monkeypatch, capsys):
    def fail(argv): raise SystemExit('cassowary failed')
    monkeypatch.setattr('dhrishti.serving.serve', lambda **kw: (None, 'http://test'))
    monkeypatch.setattr(devserver, 'run_command', fail)
    monkeypatch.setattr(devserver.time, 'sleep', lambda _: (_ for _ in ()).throw(KeyboardInterrupt))
    devserver._child(['--', 'cassowary'])
    assert 'SystemExit: cassowary failed' in capsys.readouterr().err


def test_the_env_list_covers_kernels_and_anything_that_registered(ws, monkeypatch):
    "A notebook kernel, an app leela started, and a process that called serve() are all envs."
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
    "A picked runtime has no shell channel, but its inspector owns the live namespace."
    e = _EnvClient('http://127.0.0.1:9500', 'api')
    async def answer(path, params=None, timeout=15):
        assert path == '/api/exec' and params == {'code': '1+1', 'scope': 'global'}
        return {'ok': True, 'stdout': '', 'error': None,
                'result': {'name': 'result', 'type': 'int', 'value': '2'}}
    monkeypatch.setattr(e, 'api', answer)
    r = asyncio.run(e.execute('1+1'))
    assert r.ok and r.outputs[0]['data']['text/plain'] == '2'

def _run(src_code):
    "Exec generated code the way a kernel would: one namespace, used as globals and locals."
    ns = {'__name__': '__main__'}
    exec(src_code, ns)
    return ns

def test_what_the_script_defines_stays_in_the_namespace(tmp_path):
    "The whole reason this runs in the kernel rather than in a subprocess."
    p = tmp_path / 'thing.py'
    p.write_text('x = 41\ndef bump(v): return v + 1\ny = bump(x)\n')
    ns = _run(run_file_src(p))
    assert ns['x'] == 41 and ns['y'] == 42 and callable(ns['bump'])

def test_it_runs_as_main_with_its_own_argv(tmp_path):
    "A script's `if __name__ == '__main__':` block has to run, and `sys.argv[0]` has to be the file."
    p = tmp_path / 'main.py'
    p.write_text('import sys\nran = False\nargv0 = sys.argv[0]\n'
                 "if __name__ == '__main__': ran = True\n")
    before = list(sys.argv)
    ns = _run(run_file_src(p))
    assert ns['ran'] is True
    assert ns['argv0'] == str(p)
    assert sys.argv == before, 'argv must be put back, whatever the script did with it'

def test_argv_is_restored_even_when_the_script_raises(tmp_path):
    p = tmp_path / 'boom.py'
    p.write_text('raise ValueError("nope")\n')
    before = list(sys.argv)
    with pytest.raises(ValueError): _run(run_file_src(p))
    assert sys.argv == before

def test_it_leaves_no_scaffolding_behind(tmp_path):
    "An IDE with a variable panel cannot litter the namespace it is showing you."
    p = tmp_path / 'quiet.py'
    p.write_text('a = 1\n')
    ns = _run(run_file_src(p))
    assert not [k for k in ns if k.startswith('_lee')]

def test_the_buffer_runs_rather_than_the_file_when_one_is_given(tmp_path):
    "Editing and then pressing run should run what is on the screen, not the last save."
    p = tmp_path / 'stale.py'
    p.write_text('v = "on disk"\n')
    ns = _run(run_file_src(p, src='v = "in the editor"\n'))
    assert ns['v'] == 'in the editor'

def test_the_traceback_points_at_the_file(tmp_path):
    "Compiled under the path, so an error in a script is locatable in the script."
    p = tmp_path / 'bad.py'
    p.write_text('def f():\n    return 1/0\nf()\n')
    with pytest.raises(ZeroDivisionError) as e: _run(run_file_src(p))
    assert str(p) in str(e.traceback[-1].path)

def test_run_file_code_refuses_what_it_cannot_run(ws):
    "Each refusal names the reason, because 'nothing happened' is the worst possible answer."
    assert ws.run_file_code()[0] is None
    ws.open(str(ws.fs.roots[0] / 'dialog.ipynb'))
    code, why = ws.run_file_code()
    assert code is None and 'notebook' in why
    ws.open(str(ws.fs.roots[0] / 'sample.py'))
    code, label = ws.run_file_code()
    assert code and label == 'sample.py' and 'compile(' in code

def test_the_kernel_picker_offers_this_interpreter_first(ws):
    "Whatever else is on the machine, the interpreter leela is running under always works."
    pys = find_pythons(ws.fs.roots)
    assert pys and pys[0]['path'] == sys.executable
    assert len({p['path'] for p in pys}) == len(pys), 'the same interpreter must not be listed twice'

def test_kernel_options_says_what_is_running_and_what_could(ws):
    o = ws.kernel_options()
    assert {k['id'] for k in o['kinds']} == {'ipykernel', 'ipymini'}
    assert [k for k in o['kinds'] if k['current']] == [k for k in o['kinds'] if k['id'] == 'ipykernel']
    assert any(p['current'] for p in o['pythons'])
    ipymini = next(k for k in o['kinds'] if k['id'] == 'ipymini')
    assert ipymini['available'] or ipymini['note']

def test_choosing_a_kernel_changes_what_the_next_one_starts_as(ws):
    "The pool's default is what a kernel is born with, so the picker writes there."
    ws.pool.choose(kernel='ipymini', python='/usr/bin/python3')
    assert ws.pool.default_kernel == 'ipymini' and ws.pool.default_python == '/usr/bin/python3'
    ws.pool.choose(python=None)
    assert ws.pool.default_python is None, 'None is a real choice: leela’s own interpreter'
    ws.pool.choose(kernel='nonsense')
    assert ws.pool.default_kernel == 'ipymini', 'an unknown launcher is ignored, not stored'

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

def test_debugpy_breakpoints_accept_conditions_hit_counts_and_log_messages(tmp_path, monkeypatch):
    session = DebugSession(shutil.which('python') or 'python', tmp_path)
    captured = {}
    def request(command, arguments=None, timeout=10):
        captured.update(command=command, arguments=arguments)
        return {'breakpoints': [{'verified': True, 'line': 7}]}
    monkeypatch.setattr(session, 'request', request)
    rows = session.set_breakpoints(tmp_path/'app.py', [{'line':7, 'condition':'ready',
        'hitCondition':'> 3', 'logMessage':'value={value}'}])
    assert rows[0]['verified']
    bp = captured['arguments']['breakpoints'][0]
    assert bp == {'line':7, 'condition':'ready', 'hitCondition':'> 3', 'logMessage':'value={value}'}

def completed(args, code=0, out='installed\n', err=''):
    return subprocess.CompletedProcess(args, code, out, err)

def test_project_python_probe_drops_frozen_app_redirection(monkeypatch):
    monkeypatch.setenv('PYTHONEXECUTABLE', '/Applications/Leela.app/Contents/MacOS/python')
    monkeypatch.setenv('__PYVENV_LAUNCHER__', '/Applications/Leela.app/Contents/MacOS/python')
    monkeypatch.setenv('PYTHONPATH', '/Applications/Leela.app/Contents/Resources/lib')
    seen = []
    def run(args, **kwargs):
        seen.append(kwargs['env'])
        return completed(args)
    monkeypatch.setattr(subprocess, 'run', run)
    state = support.kernel_support('/project/.venv/bin/python')
    assert state['ipykernel']['available'] and state['ipymini']['available']
    assert all('PYTHONEXECUTABLE' not in env and '__PYVENV_LAUNCHER__' not in env
               and 'PYTHONPATH' not in env for env in seen)

def test_install_prefers_uv_when_the_project_venv_has_no_pip(monkeypatch, tmp_path):
    python = tmp_path/'bin'/'python'; python.parent.mkdir(); python.write_text('')
    calls = []
    monkeypatch.setattr(support.shutil, 'which', lambda name: '/usr/local/bin/uv' if name == 'uv' else None)
    def run(args, timeout=180):
        calls.append(list(map(str, args)))
        return completed(args)
    monkeypatch.setattr(support, '_run', run)
    result = support.install_kernel_support(python)
    assert result['ok']
    assert calls[0][:5] == ['/usr/local/bin/uv', 'pip', 'install', '--python', str(python.absolute())]
    # pinned to what Leela runs, because the newest of each do not fit each other
    assert [c for c in calls[0] if c.startswith('ipykernel==')] and [c for c in calls[0] if c.startswith('ipymini==')]

def test_the_environment_leela_wires_up_actually_imports():
    from inspect import signature
    state = support.kernel_support(__import__('sys').executable)
    assert state['ipykernel']['available'], state
    assert state['ipymini']['available'], state
    for name in ('reg_dir', 'active', 'serve', 'serve_in_kernel', 'watch', 'set_kernel_backend'):
        assert callable(getattr(ds, name)), name
    params = signature(ds.serve_in_kernel).parameters
    assert {'name', 'port', 'agent', 'token', 'session_dir', 'agent_session_dir'} <= set(params)


def test_the_variable_tree_expands_values_and_survives_bad_reprs():
    assert list(PROFILES) == ['minimal', 'standard', 'full']
    assert {'name', 'recent', 'type', 'size'} <= set(SORTS)
    v = var_info('n', 42, ('n',), 'n')
    assert (v.name, v.type, v.value) == ('n', 'int', '42')
    df = var_info('df', pd.DataFrame({'a': [1, 2], 'b': [3, 4]}), ('df',), 'df')
    assert df.shape == '(2, 2)' and df.is_container
    class Boom:
        def __repr__(self): raise RuntimeError('nope')
    assert isinstance(value_str(Boom()), str)
    ns = {'d': {'a': 1}, 'df': pd.DataFrame({'revenue': [1, 2, 3]}), 'arr': np.arange(6).reshape(2, 3)}
    assert "'a'" in {c.name for c in expand(ns, ('d',))}
    assert 'revenue' in {c.name for c in expand(ns, ('df',))}
    assert grid_page(ns, ('df',))['nrows'] == 3
    assert grid_page(ns, ('arr',))['nrows'] == 2
    assert grid_page(ns, ('d',)) is None
    assert expand({'x': 1}, ('nope',)) is not None


def test_the_result_lens_keeps_an_expandable_accessor():
    "leela's result panel expands from `_`; the accessor has to survive the round trip."
    bridge = Bridge(NsClient({'_': [{'path': '/tmp/one.py'}]}))
    result = bridge.result()
    assert result.accessor == ('_',) and result.is_container
    first = bridge.expand(result.accessor)[0]
    assert first.path == '_[0]' and first.is_container
    assert bridge.expand(first.accessor)[0].path == "_[0]['path']"

def test_an_agent_write_shadows_rather_than_rebinds():
    ns = {'n': 1}
    assert Bridge(NsClient(ns)).set_value(('n',), '99') is None
    assert ns['n'] == 99
    assert Bridge(NsClient(ns)).set_value(('n',), 'this is not python') is not None
    owner = {'x': 1}
    s = AgentSession(owner=lambda: owner, log=False)
    assert s.run('x = 999').ok
    assert owner['x'] == 1, "the owner's binding must survive whatever the agent does"
    assert s.layer['x'] == 999, 'the agent should see its own value'
    owner = {'x': 1, 'xs': [1, 2]}
    s = AgentSession(owner=lambda: owner, log=False)
    s.run('del x')
    assert 'x' in owner
    assert s.run('xs.append(3)').error.startswith('blocked:')
    assert owner['xs'] == [1, 2]
    s = AgentSession(owner=lambda: {'x': 1}, log=False)
    s.run('z = 5', scope='isolated')
    assert 'z' not in s.layer


def test_leela_can_redirect_both_transcript_streams(tmp_path):
    "What the kernel bootstrap and `leela-dev` pass as session_dir/agent_session_dir."
    from dhrishti.runtime import hist_dir, agent_dir
    try:
        set_logging(dir=tmp_path/'_leela_sessions', agent_dir=tmp_path/'_leela_agent_sessions')
        assert hist_dir() == tmp_path/'_leela_sessions'
        assert agent_dir() == tmp_path/'_leela_agent_sessions'
        s = AgentSession(owner=lambda: {}, log=True)
        s.run('answer = 42')
        assert s.log_path.parent.name == '_leela_agent_sessions'
        assert s.log_path.exists()
    finally:
        set_logging(dir='_leela_sessions', agent_dir='_leela_agent_sessions')


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


def test_the_pickers_unsaved_configuration_starts_the_file_it_names(tmp_path, monkeypatch):
    """`/runs` offers a configuration for the open file so the picker is never empty, and that one is saved nowhere."""
    from types import SimpleNamespace
    root = tmp_path/'cassowary'; root.mkdir()
    main = root/'main.py'; main.write_text('print("up")\n')
    ws = Workspace(roots=[root])
    ws.open(str(main))

    started = {}
    async def fake_start(script, **kw):
        started.update(script=script, **kw)
        return SimpleNamespace(alive=True, state=lambda: {'label': 'main', 'cmd': script},
                               tail=lambda n=20: ['up'])
    monkeypatch.setattr(ws.dev, 'start', fake_start)

    with TestClient(ide_app(ws)) as client:
        here = client.get('/runs').json()['here']
        assert here and here['name'] == 'main', 'precondition: the picker offers the open file'
        r = client.get(f'/dev/start?name={here["name"]}&path={here["cmd"]}').json()
        assert r.get('ok'), r
        assert started['script'] == str(main)

        # ...and a saved name still wins, or every configuration would run as whatever file its
        # command line happens to start with.
        ws.runs.add(Run(name='api', cmd='uvicorn app:app --port 8000', watch='app'))
        assert client.get('/dev/start?name=api&path=uvicorn app:app --port 8000').json()['ok']
    assert started['script'] == 'uvicorn app:app --port 8000'


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

def test_a_run_that_succeeds_says_zero(tmp_path):
    p = tmp_path/'fine.py'; p.write_text(SCRATCH_RUNS.format(code=0))
    s = asyncio.run(_finished(DevServer(script=str(p), port=9472)))
    try: assert s.command_code == 0 and not s.running
    finally: asyncio.run(s.stop())

def test_a_run_is_on_a_terminal_its_viewers_can_attach_to(tmp_path):
    "The output is bytes on a pty, so a terminal can show it -- colour, cursor moves and all."
    p = tmp_path/'fine.py'; p.write_text(SCRATCH_RUNS.format(code=0))
    s = asyncio.run(_finished(DevServer(script=str(p), port=9473)))
    try:
        assert b'hello from the run' in bytes(s.screen)
        q = s.subscribe()
        assert q.get_nowait(), 'a late viewer is primed with what already scrolled by'
        s.unsubscribe(q); assert q not in s._subs
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
        for _ in range(50):
            if len(s1.urls) == 2: break
            await asyncio.sleep(0.1)
        assert s1.urls == ['http://127.0.0.1:8765', 'http://127.0.0.1:8766'], 'every URL a run prints, not the first'
        assert s1.app_url == 'http://127.0.0.1:8765'
        await dev.stop(str(p))
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
        for _ in range(50):
            while not q2.empty(): seen += q2.get_nowait() or b''
            if b'Uvicorn running' in seen: break
            await asyncio.sleep(0.1)
        assert b'Uvicorn running' in seen, 'a viewer that resubscribes sees the new run'
        await dev.stop_all()
    asyncio.run(asyncio.wait_for(go(), 60))

def test_the_run_socket_says_exit_when_the_run_is_stopped(tmp_path):
    "`/run/ws` used to hang on an empty queue forever, so the browser never learned the run ended."
    p = tmp_path/'srv.py'; p.write_text(SERVER_RUN.format(port=8767, port2=8768))
    ws = Workspace(roots=[tmp_path], dev_port=9476)
    with TestClient(ide_app(ws)) as c:
        info = c.get('/term/info').json()
        if not info['enabled']: pytest.skip(info['why'])
        r = c.get(f'/dev/start?path={p}').json()
        assert r['ok'], r
        try:
            with c.websocket_connect('/run/ws') as sock:
                sock.send_json({'token': info['token'], 'kind': 'run', 'cwd': str(p), 'cols': 80, 'rows': 24})
                first = sock.receive()
                assert 'bytes' in first, f'setup failed instead of attaching: {first}'
                c.get(f'/dev/stop?path={p}')
                for _ in range(200):
                    m = sock.receive()
                    if 'text' in m: break
                assert json.loads(m['text'])['t'] == 'exit'
            listed = c.get('/dev/list').json()['servers'][0]
            assert listed['running'] is False and listed['last_url'] == 'http://127.0.0.1:8767'
            assert listed['urls'] == ['http://127.0.0.1:8767', 'http://127.0.0.1:8768']
        finally: c.get(f'/dev/stop?path={p}')

def test_the_run_terminal_is_recreated_for_a_new_process():
    "Same path, new pid: the old view was attached to the old server, and `switchTerm` kept showing it."
    dock, cfg, logs = read('leela/blocks/term/dock.js'), read('leela/blocks/runs/config.js'), read('leela/blocks/runs/logs.js')
    assert 'prior.pid === pid' in dock and 'cwd: path, pid, host' in dock, 'the view remembers which process it shows'
    assert 'leeRunTerm(s.script || r.cmd, s.label, s.pid)' in cfg, 'starting a run names the process to show'
    assert 'leeRunTerm(s.script || s.path, s.label, s.pid)' in logs

def test_a_reloader_is_called_out_wherever_it_is_switched_on():
    """`--reload` in a command line was already warned about."""
    from leela.blocks.runtime.devserver import _wants_reload
    assert _wants_reload("serve('app', 'site', port=8000, reload=True)")
    assert _wants_reload('uvicorn.run(app, reload = True)')
    assert not _wants_reload("serve('app', 'site', reload=False)")
    assert not _wants_reload('print("no reloader here")')


def test_a_run_happens_in_the_project_environment_not_leelas(tmp_path):
    """A release step already resolves its interpreter from the project."""
    from leela.blocks.runtime.devserver import _boot_src, leela_path
    py = _venv(tmp_path)
    s = DevServer(script=str(tmp_path/'app.py'), python=str(py))
    cmd = s._cmd()
    assert cmd[0] == str(py) and cmd[1] == '-u' and cmd[2] == '-c', 'the project runs its own app'
    assert '-m' not in cmd, 'leela is not on that interpreter path yet, so -m cannot reach it'
    assert cmd[-1] == str(tmp_path/'app.py')
    # ...and leela is appended, so a project's copy of anything leela also ships still wins.
    boot = _boot_src(['/leela/pkgs'])
    assert 'sys.path.extend(' in boot and 'sys.path.insert' not in boot
    assert '_child(sys.argv[1:])' in boot
    assert all(os.path.isabs(p) for p in leela_path())

def test_a_run_with_no_project_interpreter_still_uses_leelas(tmp_path):
    "Nothing to resolve is not a failure; it is the old behaviour, which was right when alone."
    s = DevServer(script=str(tmp_path/'app.py'))
    assert s._cmd()[:4] == [sys.executable, '-u', '-m', 'leela.blocks.runtime.devserver']

def test_the_run_environment_points_at_the_project_venv(tmp_path):
    "PATH and VIRTUAL_ENV, so a subprocess of the app lands there too."
    from leela.blocks.runtime.kernels import venv_env
    py = _venv(tmp_path)
    env = venv_env(str(py), {'PATH': '/usr/bin'})
    assert env['VIRTUAL_ENV'] == str(tmp_path/'.venv')
    assert env['PATH'].split(os.pathsep)[0] == str(py.parent)


def test_the_header_says_what_is_running_beside_the_kernel(tmp_path):
    """A dev server has no window of its own."""
    client, _ = _client(tmp_path)
    with client as c: page = c.get('/').text
    assert 'id="runspill"' in page, 'server-rendered, so the header does not reflow on first poll'
    assert 'leeRunsMenu(this)' in page
    assert page.index('id="runspill"') < page.index('id="kpill"'), 'beside the kernel pill'

def test_the_runs_pill_reads_the_poll_that_already_runs():
    "One /dev/list poll feeds the pill, the Logs pane and the menu; a second poller would drift."
    assert read('leela/blocks/runs/logs.js').count("api('/dev/list')") == 1, \
        'the pill did not add a poller of its own'


def test_leelas_own_polling_is_not_the_apps_output():
    """The variable panel asks the inspector for /api/rows every 2.5s, and the inspector shares the app's stdout, so a run's log filled up with leela watching the run."""
    import logging, logging.config
    from uvicorn.config import LOGGING_CONFIG
    assert '/api/rows' in ds._own_paths(), 'derived from the app, not hand-copied'
    ds.quiet_access_log(); ds.quiet_access_log()
    log = logging.getLogger('uvicorn.access')
    assert sum(type(f).__name__ == '_DropOwn' for f in log.filters) == 1, 'installed once'
    logging.config.dictConfig(dict(LOGGING_CONFIG))    # the host's own uvicorn, starting after
    seen = []
    class Cap(logging.Handler):
        def emit(self, r): seen.append(r.args[2])
    log.addHandler(Cap()); log.setLevel(logging.INFO)
    try:
        for p in ('/api/rows?profile=minimal', '/agent/api/transcript', '/orders', '/'):
            log.info('%s - "%s %s HTTP/%s" %d', '127.0.0.1:1', 'GET', p, '1.1', 200)
    finally: log.removeHandler(Cap)
    assert seen == ['/orders', '/'], 'the host still logs its own traffic'
    assert 'uvicorn.access' not in read('leela/blocks/runtime/devserver.py'), 'no copy here'


def test_a_notebook_gets_its_own_repos_venv_without_being_asked(tmp_path):
    """Two folders open, each with an environment."""
    a, b = tmp_path/'first', tmp_path/'second'
    a.mkdir(); b.mkdir()
    pa, pb = _venv(a), _venv(b)
    (b/'nb.ipynb').write_text('{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}')
    ws = Workspace(roots=[a, b])
    assert ws.pool.default_python == str(pa), 'precondition: the first folder still sets the default'

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

def test_a_folder_kernel_survives_while_any_of_its_tabs_is_open(tmp_path):
    "The folder key names several tabs, so the count that matters is how many are left."
    a, b = tmp_path/'a.py', tmp_path/'b.py'
    a.write_text('a = 1\n'); b.write_text('b = 2\n')
    ws = Workspace(roots=[tmp_path])
    closed = []
    async def fake_close(key): closed.append(key)
    ws.pool.close = fake_close
    ws.open(a); ws.open(b)
    assert ws.kernel_key(ws.tabs[0]) == ws.kernel_key(ws.tabs[1]) == str(tmp_path)
    with TestClient(ide_app(ws)) as client:
        client.post('/tab/close?i=1')
        assert closed == [], 'a.py is still open on that kernel'
        client.post('/tab/close?i=0')
    assert closed == [str(tmp_path)]

class _FakeKernel:
    "Enough of a kernel for the sweep: it is alive, it can be busy, and it can be shut down."
    def __init__(self): self.alive, self._exec_task, self.shutdown_calls = True, None, 0
    async def shutdown(self): self.shutdown_calls += 1; self.alive = False

def _pooled(idle=60):
    from leela.blocks.runtime.kernels import KernelPool, _Inspector
    for n in ('touch', 'busy', 'idle_for'): setattr(_FakeKernel, n, getattr(_Inspector, n))
    return KernelPool(idle=idle)

def test_the_sweep_closes_a_kernel_nobody_has_used(tmp_path):
    """Kernels were never evicted, so a session accumulated twenty of them: 130 threads and 1.4GB before anything ran."""
    import asyncio, time
    pool = _pooled(idle=60)
    fresh, stale = _FakeKernel(), _FakeKernel()
    fresh.touch()
    stale.last_used = time.time() - 600
    pool.kernels.update({'fresh': fresh, 'stale': stale})
    assert asyncio.run(pool.reap()) == ['stale']
    assert stale.shutdown_calls == 1 and fresh.shutdown_calls == 0
    assert 'stale' not in pool.kernels and 'fresh' in pool.kernels

def test_the_sweep_never_takes_a_kernel_that_is_running_a_cell():
    "A long cell is exactly the work a person would lose, so `busy` outranks the clock."
    import asyncio, time
    pool = _pooled(idle=60)
    k = _FakeKernel(); k.last_used = time.time() - 6000
    async def go():
        k._exec_task = asyncio.create_task(asyncio.sleep(5))
        pool.kernels['busy'] = k
        assert k.busy and k.idle_for == 0
        assert await pool.reap() == []
        k._exec_task.cancel()
    asyncio.run(go())
    assert k.shutdown_calls == 0 and 'busy' in pool.kernels

def test_the_sweep_is_off_when_the_idle_window_is_zero():
    "`LEELA_KERNEL_IDLE=0` is how someone keeps every namespace for as long as leela runs."
    import asyncio, time
    pool = _pooled(idle=0)
    k = _FakeKernel(); k.last_used = time.time() - 10_000
    pool.kernels['old'] = k
    assert asyncio.run(pool.reap()) == []
    assert k.shutdown_calls == 0

def _broker_with(n, busy=(), **kw):
    "A broker over one pool holding `n` fake kernels, the named ones running a cell."
    from leela.blocks.runtime.kernels import RuntimeBroker
    import time
    b = RuntimeBroker(max_kernels=n, **kw)
    pool = _pooled(idle=0)
    b.register(pool)
    for i in range(n):
        k = _FakeKernel(); k.cwd = f'/tmp/proj{i}'; k.last_used = time.time() - (i + 1) * 100
        if i in busy: k._exec_task = object.__new__(type('T', (), {'done': lambda self: False}))
        pool.kernels[f'k{i}'] = k
    return b, pool

def test_the_kernel_limit_names_the_kernel_it_offers_to_close():
    """`admit` raised a bare RuntimeError, so the UI had nothing to offer but the text."""
    from leela.blocks.runtime.kernels import KernelLimit
    b, pool = _broker_with(3)
    with pytest.raises(KernelLimit) as e: asyncio.run(b.admit(pool, 'new'))
    assert e.value.limit == 3
    assert e.value.candidate['key'] == 'k2', 'the longest-idle one is what gets offered'
    assert e.value.candidate['name'] == 'proj2' and e.value.candidate['idle_for'] >= 300
    assert all(k.shutdown_calls == 0 for k in pool.kernels.values()), 'nothing closes without a yes'

def test_runtime_limit_is_structured_for_every_live_runtime_request(tmp_path):
    """Every request that would start a kernel says so the same way when it cannot."""
    from leela.blocks.runtime.kernels import KernelLimit
    ws = Workspace(roots=[tmp_path])
    e = KernelLimit('kernel limit reached (1)', candidate={'key': 'old', 'name': 'old', 'idle_for': 0}, limit=1)
    async def runtime(): raise e
    ws.runtime = runtime
    with TestClient(ide_app(ws)) as client:
        assert client.get('/kernel/info').status_code == 200, 'the pill never asks for one'
        assert client.get('/vars').status_code == 200
        requests = [('post', '/inspect', {'json': {'code': '', 'pos': 0}}),
                    ('post', '/vars/eval', {'json': {'code': '1'}})]
        for method, path, kw in requests:
            r = getattr(client, method)(path, **kw)
            assert r.status_code == 400 and r.json()['kernel_limit'] == 1
            assert r.json()['candidate']['key'] == 'old'


def test_kernel_info_reports_an_auto_eviction_once(tmp_path):
    "The pill peeks rather than starting one, so what it reports is the kernel the pool already has."
    from types import SimpleNamespace
    ws = Workspace(roots=[tmp_path])
    k = SimpleNamespace(alive=True, base=None, pid=1, name='new', boot_error=None, last_api_error='',
                        evicted={'key': 'old', 'name': 'old-project'})
    ws.kernel_peek = lambda tab=None: k
    with TestClient(ide_app(ws)) as client:
        assert client.get('/kernel/info').json()['evicted']['name'] == 'old-project'
        assert 'evicted' not in client.get('/kernel/info').json()


def test_auto_manage_closes_the_stalest_kernel_instead_of_asking():
    "The mute setting: leela manages the ceiling itself and never raises."
    b, pool = _broker_with(3, auto_manage=True)
    evicted = asyncio.run(b.admit(pool, 'new'))
    assert 'k2' not in pool.kernels, 'the stalest idle one made room'
    assert pool.kernels['k0'].shutdown_calls == 0 and pool.kernels['k1'].shutdown_calls == 0
    assert evicted['key'] == 'k2' and evicted['name'] == 'proj2'

def test_a_ceiling_of_busy_kernels_offers_nothing_and_says_so():
    "Nothing is safe to take, so there is no candidate and auto-manage cannot help either."
    from leela.blocks.runtime.kernels import KernelLimit
    for auto in (False, True):
        b, pool = _broker_with(2, busy=(0, 1), auto_manage=auto)
        with pytest.raises(KernelLimit) as e: asyncio.run(b.admit(pool, 'new'))
        assert e.value.candidate is None and 'busy' in str(e.value)

def test_the_auto_manage_setting_round_trips_and_reaches_the_broker(tmp_path):
    "The mute switch: saved with the workspace, and applied to the ceiling that enforces it."
    from leela.blocks.runtime.kernels import RuntimeBroker
    ws = Workspace(roots=[tmp_path])
    RuntimeBroker().register(ws.pool)
    assert ws.kernels_auto_manage is False and ws.pool.broker.auto_manage is False
    with TestClient(ide_app(ws)) as client:
        r = client.post('/runtime/auto-manage', json={'enabled': True}).json()
        assert r['ok'] and r['enabled'] is True
        assert ws.pool.broker.auto_manage is True and ws.kernels_auto_manage is True
        assert client.get('/runtime/broker').json()['auto_manage'] is True
        assert client.post('/runtime/auto-manage', json={'enabled': 'yes'}).json()['ok'] is False
    assert ws.state()['kernels_auto_manage'] is True, 'and it survives a save'

def test_the_limit_error_travels_with_the_kernel_it_offers():
    "`fail` is what every route returns, so the dialog gets its candidate wherever the limit is hit."
    import json as _json
    from leela.core.web import fail
    from leela.blocks.runtime.kernels import KernelLimit
    e = KernelLimit('kernel limit reached (12)', candidate={'key': 'k2', 'name': 'proj2',
                                                           'idle_for': 300, 'cwd': '', 'pid': 1}, limit=12)
    body = _json.loads(bytes(fail(e).body))
    assert body['ok'] is False and body['kernel_limit'] == 12
    assert body['candidate']['name'] == 'proj2' and body['candidate']['idle_for'] == 300
    plain = _json.loads(bytes(fail(ValueError('nope')).body))
    assert 'candidate' not in plain and 'kernel_limit' not in plain

def test_the_limit_dialog_can_close_the_runtime_it_was_offered(tmp_path):
    "The other half of the offer: the key it named is the key it can close."
    from leela.blocks.runtime.kernels import RuntimeBroker
    ws = Workspace(roots=[tmp_path])
    RuntimeBroker().register(ws.pool)
    from leela.blocks.runtime.kernels import _Inspector
    for n in ('touch', 'busy', 'idle_for'): setattr(_FakeKernel, n, getattr(_Inspector, n))
    k = _FakeKernel(); k.touch(); ws.pool.kernels['k9'] = k
    with TestClient(ide_app(ws)) as client:
        assert client.post('/runtime/close', json={'key': 'nope'}).json()['ok'] is False
        assert client.post('/runtime/close', json={}).json()['ok'] is False
        r = client.post('/runtime/close', json={'key': 'k9'}).json()
        assert r['ok'] and r['key'] == 'k9'
    assert k.shutdown_calls == 1 and 'k9' not in ws.pool.kernels

def test_a_busy_runtime_is_refused_even_when_named(tmp_path):
    "The offer only ever names an idle kernel, but the route is reachable on its own."
    ws = Workspace(roots=[tmp_path])
    from leela.blocks.runtime.kernels import _Inspector
    for n in ('touch', 'busy', 'idle_for'): setattr(_FakeKernel, n, getattr(_Inspector, n))
    k = _FakeKernel(); k.touch()
    k._exec_task = object.__new__(type('T', (), {'done': lambda self: False}))
    ws.pool.kernels['hot'] = k
    with TestClient(ide_app(ws)) as client:
        out = client.post('/runtime/close', json={'key': 'hot'}).json()
        # read inside: leaving the client ends the lifespan, which closes every kernel
        assert k.shutdown_calls == 0
    assert out['ok'] is False and 'running' in out['error']


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
    for name in ('runtime/app.py', 'vars/app.py'):
        src = (ROOT/'leela'/'blocks'/name).read_text()
        for route in ("@rt('/kernel/info')", "@rt('/vars')"):
            if route not in src: continue
            body = src[src.index(route):src.index('@rt', src.index(route) + 10)]
            code = '\n'.join(l for l in body.splitlines() if not l.strip().startswith(('#', '"', "'")))
            assert 'await session.runtime()' not in code, f'{route} must not start one'
            # `runtime_peek` resolves the watched environment first and, like `kernel_peek`, only
            # ever looks. Starting one is what this test forbids.
            assert '_peek()' in code, f'{route} must peek at a runtime rather than start one'


def test_a_kernel_that_cannot_import_the_inspector_is_offered_the_packages(tmp_path, monkeypatch):
    """dhrishti.core imports numpy and pandas at module level, and a kernel borrows Leela's copies over the sys.path `bootstrap_src` appends."""
    py = tmp_path/'.venv'/'bin'/'python'
    py.parent.mkdir(parents=True); py.write_text('#!/bin/sh\nexit 1\n'); py.chmod(0o755)
    ws = Workspace(roots=[tmp_path])
    class Broken:
        base, python, cwd, last_api_error = None, str(py), str(tmp_path), ''
        boot_error = "ImportError: Original error was: No module named 'numpy._core._multiarray_umath'"
        async def api(self, *a, **kw): return None
    monkeypatch.setattr(Workspace, 'kernel_peek', lambda self: Broken())
    with TestClient(ide_app(ws)) as c: d = c.get('/vars').json()
    assert d['can_install'] is True and d['packages'] == list(support.INSPECTOR)
    assert d['python'] == str(py)

def test_an_inspector_that_answered_once_is_not_offered_an_install(tmp_path, monkeypatch):
    "A failed inspector call is a live inspector that did not answer, and no package fixes that."
    py = tmp_path/'.venv'/'bin'/'python'
    py.parent.mkdir(parents=True); py.write_text('#!/bin/sh\nexit 1\n'); py.chmod(0o755)
    ws = Workspace(roots=[tmp_path])
    class Flaky:
        base, python, cwd, boot_error = 'http://127.0.0.1:1', str(py), str(tmp_path), None
        last_api_error = 'ReadTimeout: timed out'
        async def api(self, *a, **kw): return None
    monkeypatch.setattr(Workspace, 'kernel_peek', lambda self: Flaky())
    with TestClient(ide_app(ws)) as c: d = c.get('/vars').json()
    assert d['error'] == 'ReadTimeout: timed out' and 'can_install' not in d

def test_leela_never_offers_to_install_into_its_own_interpreter():
    "`pip install pandas` into a signed bundle is what `extras_site` exists to avoid."
    assert not support.installable(sys.executable)
    assert not support.installable('/Applications/Leela.app/Contents/Resources/lib/python')
    assert not support.installable('')
    assert support.installable('/project/.venv/bin/python')

def test_the_inspector_probe_borrows_the_same_paths_the_kernel_is_given(monkeypatch):
    "Probing a bare `import pandas` would nag every project whose interpreter matches Leela's."
    from leela.blocks.runtime.kernels import bootstrap_src
    assert repr(support.support_paths()) in bootstrap_src('k', 1, 'restricted', True, 'ipykernel')
    seen = []
    monkeypatch.setattr(support, '_run', lambda args, timeout=180: seen.append(list(map(str, args)))
                        or completed(args))
    support.inspector_support('/project/.venv/bin/python', refresh=True)
    assert 'import dhrishti.serving' in seen[0][-1], seen
    assert repr(support.support_paths()) in seen[0][-1]

def test_installing_the_inspector_reports_what_still_stops_it(monkeypatch, tmp_path):
    "A resolver that leaves an unusable numpy in place must not be reported as a repair."
    python = tmp_path/'bin'/'python'; python.parent.mkdir(); python.write_text('')
    monkeypatch.setattr(support.shutil, 'which', lambda n: '/usr/local/bin/uv' if n == 'uv' else None)
    calls = []
    monkeypatch.setattr(support, '_run', lambda args, timeout=180: calls.append(list(map(str, args)))
                        or completed(args))
    monkeypatch.setattr(support, 'inspector_support',
                        lambda p, refresh=False: {'available': False, 'version': '', 'error': 'wrong ABI'})
    with pytest.raises(RuntimeError, match='still will not import: wrong ABI'):
        support.install_inspector_support(python)
    assert calls[0][:5] == ['/usr/local/bin/uv', 'pip', 'install', '--python', str(python.absolute())]
    assert list(support.INSPECTOR) == [c for c in calls[0] if c in support.INSPECTOR]

def test_creating_a_venv_does_not_install_numpy_and_pandas_unasked(tmp_path, monkeypatch):
    """`checkProjectRuntime` runs `/runtime/create` without asking when uv is there, on the rule that a directory it made is a directory it may fill."""
    python = tmp_path/'bin'/'python'; python.parent.mkdir(); python.write_text('')
    calls = []
    monkeypatch.setattr(support.shutil, 'which', lambda n: '/usr/local/bin/uv' if n == 'uv' else None)
    monkeypatch.setattr(support, '_run', lambda args, timeout=180: calls.append(list(map(str, args)))
                        or completed(args))
    support.install_kernel_support(python)
    assert not any(p in c for c in calls for p in support.INSPECTOR), calls
    src = (ROOT/'leela'/'blocks'/'runtime'/'app.py').read_text()
    assert "@rt('/runtime/inspector')" in src and 'install_inspector_support' in src


def test_a_kernel_of_another_python_borrows_nothing_from_leela():
    """Leela's `sys.path` was appended to every kernel."""
    from leela.blocks.runtime.kernels import bootstrap_src
    from leela.blocks.runtime.support import LEELA_PY
    src = bootstrap_src(name='t')
    assert f'tuple(sys.version_info[:2]) == tuple({LEELA_PY!r})' in src, 'the paths are guarded'
    guard, borrow = src.index('tuple(sys.version_info[:2]) =='), src.index('sys.path.append')
    assert guard < borrow, 'and guarded before they are borrowed, not after'
    assert src.count('tuple(sys.version_info[:2])') >= 2, 'the dhrishti pin is guarded too'

def test_a_new_environment_gets_the_kernel_versions_leela_itself_runs():
    """Resolving the declared requirements gave `ipymini 0.1.20` beside `kernmini 0.1.9`, which import each other and do not fit: `ipymini` imports `kernmini.debug`, and 0.1.9 does not ship it."""
    import importlib.metadata as md
    from kunda.support import KERNEL_PACKAGES, as_installed
    assert set(KERNEL_PACKAGES) >= {'ipykernel', 'ipymini', 'kernmini', 'fastcore', 'microio'}
    pinned = dict(spec.split('==') for spec in as_installed() if '==' in spec)
    for name in KERNEL_PACKAGES:
        assert pinned[name] == md.version(name), f'{name} is pinned to the one Leela runs'
    loose = as_installed(('ipykernel', 'no-such-distribution-at-all'))
    assert loose[-1] == 'no-such-distribution-at-all', 'and a name Leela lacks is left to resolve'

def test_an_installed_kernel_that_will_not_import_is_reported_as_that(monkeypatch, tmp_path):
    """The installer returned 0 but reached the person as `No module named pip` from the fallback, a report about pip a uv env never has rather than the package that fails."""
    from kunda import support
    monkeypatch.setattr(support, '_run', lambda args, timeout=180: completed(args))
    monkeypatch.setattr(support, 'kernel_support', lambda python: {
        'ipykernel': {'available': True, 'version': '7.3.0', 'error': ''},
        'ipymini': {'available': False, 'version': '', 'error': "ModuleNotFoundError: No module named 'kernmini.debug'"}})
    with pytest.raises(RuntimeError) as caught:
        support.install_kernel_support(tmp_path/'.venv'/'bin'/'python')
    said = str(caught.value)
    assert 'ipymini installed but does not import' in said and 'kernmini.debug' in said
    assert 'pip' not in said, 'the fallback installer is not the news'

def test_the_inspector_a_project_must_install_is_the_one_it_cannot_borrow():
    "numpy and pandas are what is noticed missing; dhrishti is what actually has to be there."
    from kunda.support import INSPECTOR
    assert INSPECTOR == ('dhrishti',)

def test_the_inspector_probe_asks_the_question_the_kernel_asks(monkeypatch):
    "A probe that extends the path where the kernel would not is a probe answering for nobody."
    from kunda import support
    seen = {}
    class Done:
        returncode, stdout, stderr = 0, '1.0', ''
    def fake(args, timeout=180): seen['code'] = args[-1]; return Done()
    monkeypatch.setattr(support, '_run', fake)
    monkeypatch.setattr(support, '_INSPECT', {})
    support.inspector_support('/somewhere/python', refresh=True)
    assert 'sys.version_info[:2]' in seen['code'], 'the probe is version-guarded like the bootstrap'
    assert seen['code'].index('sys.version_info[:2]') < seen['code'].index('sys.path.extend')

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
    assert r['note'] == 'released 1 model engine' and engine.closed

def test_a_session_on_a_model_refuses_the_clear_and_names_it(tmp_path, monkeypatch):
    "The same 409 shape every answerable refusal uses, naming what is holding the weights."
    engine, be = _loaded_engine(monkeypatch, live=True)
    with _client(tmp_path)[0] as c: r = c.post('/runtime/engines/clear', json={})
    assert r.status_code == 409 and r.json()['ok'] is False
    assert 'mlx/qwen' in r.json()['error'] and not engine.closed

def test_a_forced_clear_closes_the_model_a_session_is_on(tmp_path, monkeypatch):
    engine, be = _loaded_engine(monkeypatch, live=True)
    with _client(tmp_path)[0] as c: r = c.post('/runtime/engines/clear', json={'force': True}).json()
    assert r['ok'] and r['freed'] == [{'runtime': 'mlx', 'model': 'qwen'}] and engine.closed

def test_clearing_nothing_says_nothing_was_loaded(tmp_path, monkeypatch):
    from leela.blocks.runtime import engines as eng
    monkeypatch.setattr(eng, '_BROKER', eng.EngineBroker(max_engines=3))
    with _client(tmp_path)[0] as c: r = c.post('/runtime/engines/clear', json={}).json()
    assert r['ok'] and r['freed'] == [] and r['note'] == 'no model weights were loaded'

def _kernel_js(): return read('leela/blocks/runtime/kernel.js')

def test_the_kernel_picker_lists_the_loaded_models_and_can_clear_them():
    "`/runtime/broker` reported the loaded weights to nobody: no JS asked for them. This is the caller."
    src = _kernel_js()
    assert "api('/runtime/broker')" in src and 'engineSection(models)' in src
    sec = src[src.index('function engineSection('):src.index('async function clearEngines(')]
    for field in ('runtime', 'model', 'in_use', 'idle_for', 'live', 'limit'): assert field in sec, field
    assert "id=\"clearengines\"" in sec

def test_an_unhappy_broker_does_not_keep_the_kernel_picker_shut():
    "The picker is where a person goes when a runtime is misbehaving. It must open without the weights."
    src = _kernel_js()
    block = src[src.index('async function loadedModels('):src.index('function engineSection(')]
    assert 'catch' in block and 'return null' in block, 'a broker that cannot answer must not throw here'
    assert "if (!models) return '';" in src, 'and the section is then simply not painted'

def test_a_row_of_loaded_weights_does_not_restart_the_kernel():
    "The picker's one click handler takes every `.lee-mrow`, and a model row is not a kernel choice."
    src = _kernel_js()
    assert "if (!r || r.dataset.engine) return;" in src
    assert "data-engine=\"1\"" in src

def test_the_refusal_is_shown_and_the_force_is_a_second_answer():
    "A 409 carries the sentence naming what holds the weights. It is what the person is asked about."
    src = _kernel_js()
    block = src[src.index('async function clearEngines('):src.index('/* The kernel ceiling')]
    assert 'const refusal = String(e.message || e);' in block, 'the server sentence, not a bare failure'
    assert 'confirmDialog(' in block and 'refusal' in block.split('confirmDialog(')[1][:200]
    assert "post('/runtime/engines/clear', {force: true})" in block
    assert block.count("status(refusal, 'err')") == 2, 'shown when it cannot be answered, and when declined'
    assert 'd.freed' in block and 'd.live' in block, 'and the outcome says what went'

def test_the_broker_reports_the_engine_fields_the_picker_paints(tmp_path, monkeypatch):
    "The contract the model list is drawn from, pinned where the route can see it."
    engine, be = _loaded_engine(monkeypatch, live=True)
    with _client(tmp_path)[0] as c: d = c.get('/runtime/broker').json()
    assert d['models']['live'] == 1 and d['models']['limit'] == 3
    e = d['models']['engines'][0]
    assert e['runtime'] == 'mlx' and e['model'] == 'qwen' and e['in_use'] is True
    assert isinstance(e['idle_for'], int) and e['users'] == 1

def _bare_venv(tmp_path):
    "A real interpreter with nothing installed in it, which is what a pruned project venv is."
    import venv
    venv.create(tmp_path/'v', with_pip=False)
    return first(p for p in (tmp_path/'v'/'bin'/'python', tmp_path/'v'/'Scripts'/'python.exe') if p.exists())

def test_an_environment_that_cannot_run_a_kernel_says_which_module_it_is_short_of(tmp_path):
    """`uv sync` against another lock empties a project venv, and the kernel then exits before its first message."""
    from leela.blocks.runtime.kernels import missing_kernel_module
    assert missing_kernel_module(sys.executable) is None, "leela's own interpreter has ipykernel"
    py = _bare_venv(tmp_path)
    assert missing_kernel_module(str(py)) == 'ipykernel_launcher'
    assert missing_kernel_module(str(py), kernel='ipymini') == 'ipymini'
    assert missing_kernel_module(str(tmp_path/'not-an-interpreter')) is None, \
        'an interpreter that cannot be asked is not evidence of a missing module'

def test_a_kernel_in_an_emptied_venv_fails_with_the_venv_and_not_the_protocol(tmp_path):
    "It reported `Kernel died before replying to kernel_info`, which names the handshake, not the cause."
    from leela.blocks.runtime.kernels import Kernel, KernelStartError
    py = _bare_venv(tmp_path)
    with pytest.raises(KernelStartError) as e:
        asyncio.run(Kernel(python=str(py), inspect=False).start(timeout=10))
    assert 'ipykernel_launcher' in str(e.value) and str(py) in str(e.value)
    assert 'uv sync' in str(e.value), 'and it names the way out'

def test_every_way_a_child_gets_its_environment_leaves_the_bundle_behind(monkeypatch):
    """The first fix only covered the default."""
    from leela.blocks.runtime.kernels import venv_env
    from kunda.pythons import BUNDLE_ONLY, strip_bundle
    for k in BUNDLE_ONLY: monkeypatch.setenv(k, '/bundle')
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    for env in (venv_env('/tmp/p/.venv/bin/python'),          # the default
                venv_env(None),                                # a folder with no project interpreter
                venv_env('/tmp/p/.venv/bin/python', {**os.environ}),   # the dev server's explicit dict
                strip_bundle({**os.environ})):
        assert not [k for k in BUNDLE_ONLY if k in env], f'the bundle reached a child: {env}'

def test_the_pipeline_routes_run_a_child_with_that_environment():
    "`nbdev-prepare` and the ship steps take their own route, and it went around the pty's environment."
    src = (ROOT/'leela'/'blocks'/'pipelines'/'app.py').read_text()
    runs = [l for l in src.splitlines() if 'subprocess.run(' in l]
    assert runs, 'the routes still spawn something'
    for line in runs:
        block = src[src.index(line):src.index(line) + 400]
        assert 'env=' in block, f'a child with no environment of its own: {line.strip()}'

def test_a_frozen_app_hands_a_child_its_own_interpreter_and_not_the_bundles(monkeypatch):
    """py2app points `PYTHONPATH`, `PYTHONHOME` and `__PYVENV_LAUNCHER__` at the bundle so its helper starts."""
    from leela.blocks.runtime.kernels import venv_env
    for k, v in {'PYTHONPATH': '/bundle/lib', 'PYTHONHOME': '/bundle', 'RESOURCEPATH': '/bundle',
                 '__PYVENV_LAUNCHER__': '/bundle/python', 'PYTHONEXECUTABLE': '/bundle/python'}.items():
        monkeypatch.setenv(k, v)
    kept = venv_env('/tmp/project/.venv/bin/python')
    assert kept['PYTHONPATH'] == '/bundle/lib', 'a normal install has one environment and keeps it'

    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    env = venv_env('/tmp/project/.venv/bin/python')
    for name in ('PYTHONPATH', 'PYTHONHOME', 'RESOURCEPATH', '__PYVENV_LAUNCHER__', 'PYTHONEXECUTABLE'):
        assert name not in env, f'{name} reached the child'
    assert env['VIRTUAL_ENV'] == '/tmp/project/.venv', 'and the project venv is still what it runs in'
    assert env['PATH'].split(os.pathsep)[0] == '/tmp/project/.venv/bin'


def test_a_frozen_app_starts_children_somewhere_they_can_write(monkeypatch, tmp_path):
    """A double-clicked app inherits `/` as its working directory and one opened from the bundle inherits the bundle, which is read-only."""
    from kunda.support import work_dir
    assert work_dir(tmp_path) == str(tmp_path), 'a chosen directory is never second-guessed'
    monkeypatch.chdir(tmp_path)
    assert work_dir() == os.getcwd(), 'unfrozen, the working directory is the answer'
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    assert work_dir() == os.getcwd(), 'a writable one is still the answer'
    monkeypatch.chdir(os.sep)
    assert work_dir() == str(Path.home()), 'from `/`, somewhere a child can write'
    assert work_dir(tmp_path) == str(tmp_path)

def test_a_devserver_child_borrows_leelas_path_only_on_leelas_python():
    """`_boot_src` runs under the project's interpreter."""
    from leela.blocks.runtime.devserver import _boot_src
    from leela.blocks.runtime.support import LEELA_PY
    src = _boot_src(['/somewhere/leela'])
    assert f'if tuple(sys.version_info[:2]) == {LEELA_PY!r}:' in src
    guard, extend = src.index('sys.version_info'), src.index('sys.path.extend')
    assert guard < extend, 'the version is asked before the path is taken'
    ns = {}
    exec(src.split('from leela')[0], ns)          # the guard alone, under this interpreter
    assert '/somewhere/leela' in ns['sys'].path
    ns['sys'].path.remove('/somewhere/leela')
