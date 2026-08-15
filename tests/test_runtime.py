"Runtimes: project kernels, tab bindings, run configurations, the debugger."

import json
import os
import shutil
from pathlib import Path
import pytest
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.blocks.runtime.kernels import nearest_python, project_python
from leela.workspace import Workspace
from tests.assets import CSS, JS, SERVER
import asyncio
import sys
from fastcore.all import Path
from leela.blocks.runtime import devserver
from leela.blocks.runtime.devserver import DevServer, DevServers, infer_watch, run_command, split_cmd
from leela.blocks.runs.runs import RUNS_FILE, Run, Runs
from leela.workspace import _EnvClient
from leela.blocks.runtime.kernels import find_pythons, run_file_src
from leela.blocks.debug.debug import DebugSession, debugpy_available
import subprocess
from leela.blocks.runtime import support as support
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

def test_the_client_creates_without_asking_only_when_uv_can_do_it():
    "The dialog stays for the two cases that must remain a choice."
    block = JS[JS.index('async function checkProjectRuntime'):]
    block = block[:block.index('/* ------------------------------------------------------------------ boot */')]
    assert 'if (d.needs_create && d.uv) {' in block, 'automatic, and only with uv'
    assert "post('/runtime/create')" in block
    assert block.index('if (d.needs_create && d.uv)') < block.index('if (d.needs_support)'), \
        'the automatic path runs before any dialog is built'
    assert 'runtimepick' in block, 'choosing an interpreter is still offered when creation fails'

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
    env = venv_env(str(py), {'PATH': '/usr/bin', 'PYTHONHOME': '/somewhere/else'})
    assert env['VIRTUAL_ENV'] == str(tmp_path/'.venv') == env['UV_PROJECT_ENVIRONMENT']
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

def test_a_git_terminal_gets_the_project_environment_too(tmp_path):
    "lazygit commits, and a commit runs the project's hooks -- a tab that is not a shell still needs."
    assert "env = venv_env(py) if py else None" in SERVER, 'no kind is excluded'
    assert "prelude = path_prelude(py, shell.get('shell')) if argv is None else ''" in SERVER

def test_git_itself_runs_with_the_checkouts_environment(tmp_path):
    "A hook is a console script of the repository being committed to, not of Leela."
    from leela.blocks.git.git import gateway          # importing the block is what wires `env_for`
    g = gateway()
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
    assert 'find_repo:' in JS and 'async function findRepo' in JS, 'and it is dispatchable'

def test_the_runtime_list_is_asked_of_ramabana_not_duplicated(tmp_path):
    "leela's copy of the runtime list drifted twice."
    from leela.blocks.agent.models import runtimes
    from leela.agent.core import RUNTIMES, runtime_available
    got = {r['value']: r['available'] for r in runtimes()}
    assert tuple(got) == tuple(RUNTIMES), 'exactly what register_model accepts, in its order'
    for name, avail in got.items():
        assert avail is bool(runtime_available(name)), f'{name} must report what rishi says'
    assert got['remote'] is True

def test_the_model_dialog_is_told_which_runtimes_exist(tmp_path):
    from leela.agent.core import RUNTIMES
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as c: d = c.get('/agent/models').json()
    assert [r['value'] for r in d['runtimes']] == list(RUNTIMES)
    assert 'd.runtimes' in JS, 'and it builds the select from that rather than a hardcoded list'
    # The remedy moved to the server with the label: `pip install rishi[cursor]` is not how you
    # get the Cursor agent, and the browser had no way to know that.
    why = {r['value']: r['why'] for r in d['runtimes']}
    assert 'rishi[mlx]' in why['mlx'], 'saying what to install for the ones that are missing'
    assert 'CLI or SDK' in why['cursor'] and 'CLI or SDK' in why['claude']

def test_choosing_the_litert_accelerator_is_remembered_and_exported(tmp_path, monkeypatch):
    "ramabana reads $LEELA_LITERT_BACKEND when it builds an engine."
    monkeypatch.delenv('LEELA_LITERT_BACKEND', raising=False)
    ws = Workspace(roots=[tmp_path]); ws._state_path = tmp_path/'ws.json'
    with TestClient(ide_app(ws)) as c:
        assert c.post('/agent/settings', json={'litert_backend': 'gpu'}).json()['litert_backend'] == 'gpu'
    import os
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

def test_the_repository_search_is_debounced_and_says_it_is_running():
    "One search per word, not per keystroke, and a banner while it runs."
    block = JS[JS.index('async function addRoot'):]
    block = block[:block.index('\ndocument.addEventListener')]
    assert 'setTimeout(() => repos(frag), 200)' in block, 'debounced, not per keystroke'
    assert 'clearTimeout(timer)' in block, 'and the pending one is dropped'
    assert 'lee-searching' in block and 'searching' in block, 'it says a search is running'
    assert 'if (mine !== seq) return' in block, 'a late answer never overwrites a newer one'
    assert '.lee-searching' in CSS and '.lee-spin' in CSS

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
    assert 'catch (e)' in block, 'a failure has to reach the status line'
    assert "leeFail('git', name, e)" in block, 'with its whole detail, in the log'
    assert block.index('catch (e)') < block.index('finally'), 'caught before busy is cleared'
    block = JS[JS.index('async function pollRunLogs'):]
    block = block[:block.index('function leeDock')]
    assert "(await api('/dev/list')).servers" in block, 'managed runs are retained even while Logs is closed'
    assert 'lee.runSeen' in block, 'and only new lines are appended'
    assert 'lee.runFinished' in block, 'a completed run is notified once'
    assert 'prelude' in SERVER, 'the pty takes one'
    assert 'os.write(master, self.prelude.encode()' in SERVER, 'written after the shell starts'
    assert 'export PATH=' in SERVER and '$PATH' in SERVER
    assert shell_argv('/opt/homebrew/bin/fish') == ['/opt/homebrew/bin/fish', '-l']
    assert shell_argv('/bin/bash', login=False) == ['/bin/bash']
    assert shell_argv('/bin/bash', ['-i', '-c', 'true']) == ['/bin/bash', '-i', '-c', 'true']
    assert shell_argv('', (), True) == [default_shell(), '-l'], 'empty means $SHELL'
    assert "id='termexternal'" in SERVER and 'leeExternalTerm()' in SERVER
    block = JS[JS.index('async function leeExternalTerm'):JS.index('function leeNewTerm')]
    assert "post('/term/external')" in block
    open_block = JS[JS.index('async function openTerm'):JS.index('async function openReleaseTerm')]
    assert "external.hidden = !(d.external || []).length" in open_block


def test_a_workspace_operation_names_the_repositories_it_is_working_on():
    "A fan-out over several checkouts always raises the question of which one is slow."
    block = JS[JS.index('async function gitReposDo('):]
    block = block[:block.index('// Pinning is a scope change')]
    assert 'reposBusy' in block, 'the rows are marked while the operation runs'
    assert "'repositories'" in block and 'targets.length' in block, 'and the status says how many'
    assert 'finally' in block and 'gitUI.reposBusy = null' in block, 'always cleared'
    assert "gitUI.reposBusy?.has(r.root)" in JS, 'the row renders it'
    assert '.lee-git-repo-row.working' in CSS

def test_the_logs_pane_holds_what_a_status_line_cannot():
    "Git's refusals are multi-line and the useful part is the file list; a toast clips it."
    assert 'lee-logpanel' in SERVER and "data_dock='logs'" in SERVER, 'a third dock tab'
    assert 'data_log_filter' in SERVER and "history" in SERVER, 'commit history is separate from git activity'
    assert 'function leeLog(' in JS and 'renderLogs' in JS
    assert "api('/git/history?limit=100" in JS, 'the history filter reads the selected repository'
    assert "leeLog('git'" in JS, 'git actions log their detail'
    assert "api('/dev/log" in JS, 'and the run log route finally has a reader'
    assert 'srv.returncode' in JS and "leeDock('logs')" in JS, 'a failed managed run notifies through Logs'
    assert 'showLog(' in JS and 'firstLine(detail)' in JS
    assert '.lee-logdetail' in CSS and 'pre-wrap' in CSS, 'the detail is not clipped'

def test_picking_logs_shows_the_logs_and_not_the_pane_it_replaced():
    "`.lee-execstrip` names no element, so Logs hid the terminal and left exec in its place."
    assert '.lee-execstrip' not in CSS, 'the dock hides the exec pane by the class the shell renders'
    assert 'lee-panel lee-exec' in SERVER
    rule = CSS[CSS.index('.lee-bottomdock.dock-logs'):CSS.index('.lee-logpanel { display: none')]
    for cls in ('.lee-exec', '.lee-termpanel'): assert cls in rule, f'{cls} stays visible under Logs'
    fill = CSS[CSS.index('.lee-bottomdock .lee-dockbody > '):]
    assert '.lee-logpanel' in fill[:fill.index('}')], 'and Logs fills the dock like the panes it replaces'


def test_a_terminal_tab_closes_itself():
    "One × in the header could only shut the active terminal; closing a background one meant."
    block = JS[JS.index('function paintTermTabs'):]
    block = block[:block.index('function leeLeft')]
    assert 'data-term-close' in block and 'data-term-pick' in block
    assert 'e.stopPropagation()' in block, 'closing a tab must not also select it'
    assert 'closeTerm(b.dataset.termClose)' in block
    assert "close active terminal" not in SERVER, 'the header control is gone'


def test_the_folder_picker_is_one_box_that_completes_as_you_type():
    "A path bar, a filter box, a list and an up button were four controls for one question."
    block = JS[JS.index('async function addRoot'):]
    block = block[:block.index('\ndocument.addEventListener')]
    assert 'lee-pathinput' in block and 'folderfilter' not in block, 'one box, not two'
    assert "e.key === 'Tab'" in block and 'const complete = ()' in block, 'Tab completes'
    assert "e.key === 'Enter'" in block and 'return open(v)' in block, 'Enter opens'
    assert "e.key === 'ArrowDown'" in block, 'and the list is reachable from the keyboard'
    assert 'dirs.some(x => x.path === v.replace' in block, \
        'a path that names a folder opens; a half-typed one completes first'
    assert 'activateRoot(target)' in block, 'opening a folder is also choosing that project'
    assert '.lee-folderrow.sel' in CSS

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

def test_opening_a_folder_redraws_the_tree_before_selecting_the_new_root():
    "Order matters: activating selects the new root's node, which must exist by then."
    block = JS[JS.index('async function addRoot'):]
    block = block[:block.index('\ndocument.addEventListener')]
    body = block[block.index('const open = async path =>'):block.index('input.oninput = draw')]
    assert "await post('/fs/add-root'" in body
    assert body.index('refreshFileTree(target)') < body.index('activateRoot(target)'), \
        'the tree is rebuilt before the new root is selected in it'

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
    from leela.blocks.term.term import Terminals
    terms = Terminals(cwd=tmp_path)
    terms.open('term-1', argv=['/bin/sh', '-c', 'sleep 30'])
    try:
        states = terms.states()
        assert [s['id'] for s in states] == ['term-1']
        assert states[0]['alive'] is True and states[0]['pid']
    finally:
        terms.close_all()
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

def test_a_notebook_gets_its_own_project_venv_not_the_last_one_chosen(tmp_path):
    "The reported failure: opening a notebook under `nbs/` ran it in another checkout's venv."
    from leela.blocks.runtime.kernels import nearest_python, python_for
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
    import asyncio
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
    assert 'ipykernel>=7.3.0' in calls[0] and 'ipymini>=0.0.1' in calls[0]

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
        set_logging(dir=tmp_path/'leela_sessions', agent_dir=tmp_path/'leela_agent_sessions')
        assert hist_dir() == tmp_path/'leela_sessions'
        assert agent_dir() == tmp_path/'leela_agent_sessions'
        s = AgentSession(owner=lambda: {}, log=True)
        s.run('answer = 42')
        assert s.log_path.parent.name == 'leela_agent_sessions'
        assert s.log_path.exists()
    finally:
        set_logging(dir='leela_sessions', agent_dir='leela_agent_sessions')
