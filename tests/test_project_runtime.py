"""Opening a folder with no environment gets one, rather than falling back to PATH.

The failure this prevents is quiet: `project_python` returns None, `pool.default_python` stays
None, and the kernel launches under whatever `python3` resolves to on PATH -- often a system
3.8 with none of the project's dependencies. Nothing errors; the notebook just runs somewhere
nobody chose.
"""

import json
import os
import shutil
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from leela.app import ide_app
from leela.blocks.runtime.kernels import project_python
from leela.workspace import Workspace
from tests.assets import CSS, JS, SERVER


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
    # An executable stub, because `/runtime/info` really does run the interpreter to ask what
    # kernel packages it has. Exiting non-zero is the honest answer for a venv without them.
    py = tmp_path/'.venv'/'bin'/'python'
    py.parent.mkdir(parents=True)
    py.write_text('#!/bin/sh\nexit 1\n'); py.chmod(0o755)
    client, ws = _client(tmp_path)
    with client as c: d = c.get('/runtime/info').json()
    assert d['needs_create'] is False
    assert d['python'] == str(py) and ws.pool.default_python == str(py)


def test_the_client_creates_without_asking_only_when_uv_can_do_it():
    """The dialog stays for the two cases that must remain a choice.

    `needs_support` installs into an environment the developer built, and no-uv would leave a
    half-built venv behind; both still ask. A missing environment with uv available does not.
    """
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
    """One workspace, several checkouts, one environment each.

    `/git/repos` exists because a workspace holds more than one repository, and each has its
    own venv. Keying the shell to `pool.default_python` put every terminal in the *first*
    root's environment no matter where it was opened.
    """
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
    """The reported failure: `nbdev_prepare` from a system Python 3.8.

    A release step is a console script resolved by PATH, so a pipeline holding
    `pool.default_python` -- the *first* root's venv, or None until something chose -- ran the
    wrong one. It resolves the interpreter from the project root, exactly as a terminal does.
    """
    from leela.blocks.pipelines.releases import Release
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
    "lazygit commits, and a commit runs the project's hooks -- a tab that is not a shell still needs the venv."
    assert "env = venv_env(py) if py else None" in SERVER, 'no kind is excluded'
    # Only a shell is typed into: keystrokes would land in lazygit's UI or gh's prompt. The line
    # itself is `path_prelude`'s job, because what to type depends on which shell is reading it.
    assert "prelude = path_prelude(py, shell.get('shell')) if argv is None else ''" in SERVER


def test_git_itself_runs_with_the_checkouts_environment(tmp_path):
    """A hook is a console script of the repository being committed to, not of Leela.

    The gateway owns this because it is the only thing that runs Git, and because the same
    environment decides whether a clean filter can run at all -- which is what `filter_health`
    asks it about.
    """
    from leela.blocks.git.safety import GitGateway
    g = GitGateway()
    root = tmp_path/'proj'; py = _venv(root); (root/'.git').mkdir()
    env = g.env(root/'sub'/'deeper')
    assert env['PATH'].split(os.pathsep)[0] == str(py.parent), 'found by searching upwards'
    bare = tmp_path/'bare'; (bare/'.git').mkdir(parents=True)
    assert g.env(bare) is None, 'no venv, nothing claimed -- git inherits what Leela has'
    # And the probe that explains a dirtying filter asks about *that* PATH, not Leela's.
    assert g.resolves(root/'sub', 'definitely-not-installed-anywhere') == ''


# ---------------------------------------------------------------- finding a checkout

def test_find_repos_searches_deeper_than_discover_and_filters_by_name(tmp_path):
    """`discover` is one level deep by design; finding a checkout you half-remember is not.

    The dialog's filter is the whole point of this: a directory of clones is nested, and
    `discover` would only ever see the first level of it.
    """
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
    """Browsing is `o` in the files panel; this is the other way in and must be global.

    A bare letter cannot bind globally -- it would fire while typing -- so this is its own
    action with a modifier rather than a second chord on add_root, which the keymap forbids
    anyway: one entry per action.
    """
    from leela.core.keys import KEYS, chord_display
    find = [k for k in KEYS if k.action == 'find_repo']
    assert len(find) == 1 and find[0].scope == 'global'
    assert chord_display('find_repo') and 'o' in chord_display('find_repo')
    assert [k.scope for k in KEYS if k.action == 'add_root'] == ['files'], 'browsing stays where it was'
    assert 'find_repo:' in JS and 'async function findRepo' in JS, 'and it is dispatchable'


# ---------------------------------------------------------------- runtimes and accelerators

def test_the_runtime_list_is_asked_of_ramabana_not_duplicated(tmp_path):
    """leela's copy of the runtime list drifted once already.

    ramabana dropped MLX and llama.cpp; leela kept offering both, so the picker had two
    choices that could only fail at save time. `runtimes()` asks instead, and reports which
    ones rishi can actually load here.
    """
    from leela.blocks.agent.models import runtimes
    from leela.agent.core import runtime_available
    got = {r['value']: r['available'] for r in runtimes()}
    assert set(got) == {'litert', 'mlx', 'llama', 'remote'}, 'everything register_model accepts'
    for name, avail in got.items():
        assert avail is bool(runtime_available(name)), f'{name} must report what rishi says'
    assert got['remote'] is True


def test_the_model_dialog_is_told_which_runtimes_exist(tmp_path):
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as c: d = c.get('/agent/models').json()
    assert [r['value'] for r in d['runtimes']] == ['litert', 'mlx', 'llama', 'remote']
    assert 'd.runtimes' in JS, 'and it builds the select from that rather than a hardcoded list'
    assert 'rishi[' in JS, 'saying what to install for the ones that are missing'


def test_choosing_the_litert_accelerator_is_remembered_and_exported(tmp_path, monkeypatch):
    """ramabana reads $LEELA_LITERT_BACKEND when it builds an engine.

    So the setting has to reach the environment, not just the workspace -- and it has to
    survive a reload, since the whole point is that GPU is materially faster here.
    """
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
    """One search per word, not per keystroke, and a banner while it runs.

    Searching from a home directory takes most of a second. Firing one per keystroke queued
    five of them behind a single worker for a five-letter name, which is what made this feel
    broken. A running search and an empty result also look identical without the banner.
    """
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


def test_a_failed_git_action_says_so_instead_of_looking_stalled():
    """A refused checkout is a fast, normal answer. It must not read as a hang.

    `gitDo` had a try/finally and no catch, so a rejected operation left the status line
    saying "git checkout…" for ever while the exception went past it -- indistinguishable
    from a git subprocess that never returned. `gitReposDo` beside it already caught, which
    is why fetching every repository behaved and switching a branch appeared to stall.
    """
    block = JS[JS.index('async function gitDo('):]
    block = block[:block.index('\nfunction gitOperationBanner')]
    assert 'catch (e)' in block, 'a failure has to reach the status line'
    assert 'failed' in block and "'err'" in block
    assert block.index('catch (e)') < block.index('finally'), 'caught before busy is cleared'


def test_a_workspace_operation_names_the_repositories_it_is_working_on():
    "A fan-out over several checkouts always raises the question of which one is slow."
    block = JS[JS.index('async function gitReposDo('):]
    block = block[:block.index('// Pinning is a scope change')]
    assert 'reposBusy' in block, 'the rows are marked while the operation runs'
    assert "'repositories'" in block and 'targets.length' in block, 'and the status says how many'
    assert 'finally' in block and 'gitUI.reposBusy = null' in block, 'always cleared'
    assert "gitUI.reposBusy?.has(r.root)" in JS, 'the row renders it'
    assert '.lee-git-repo-row.working' in CSS


# ---------------------------------------------------------------- logs, terminals

def test_the_logs_pane_holds_what_a_status_line_cannot():
    """Git's refusals are multi-line and the useful part is the file list; a toast clips it.

    `/dev/log` had also been serving what dev servers print since it was written, with
    nothing in the browser reading it.
    """
    assert 'lee-logpanel' in SERVER and "data_dock='logs'" in SERVER, 'a third dock tab'
    assert 'function leeLog(' in JS and 'renderLogs' in JS
    assert "leeLog('git'" in JS, 'git actions log their detail'
    assert "api('/dev/log" in JS, 'and the run log route finally has a reader'
    # The toast used to say "see logs" and leave you to find them. It now carries git's first
    # line and the failure opens the pane itself; see test_web_project_tools.py.
    assert 'showLog(' in JS and 'firstLine(detail)' in JS
    assert '.lee-logdetail' in CSS and 'pre-wrap' in CSS, 'the detail is not clipped'


def test_the_run_log_tail_costs_nothing_while_the_pane_is_closed():
    block = JS[JS.index('async function pollRunLogs'):]
    block = block[:block.index('function leeDock')]
    assert "classList.contains('dock-logs')" in block and 'return' in block
    assert 'lee.runSeen' in block, 'and only new lines are appended'


def test_a_terminal_tab_closes_itself():
    "One × in the header could only shut the active terminal; closing a background one meant selecting it."
    block = JS[JS.index('function paintTermTabs'):]
    block = block[:block.index('function leeLeft')]
    assert 'data-term-close' in block and 'data-term-pick' in block
    assert 'e.stopPropagation()' in block, 'closing a tab must not also select it'
    assert 'closeTerm(b.dataset.termClose)' in block
    assert "close active terminal" not in SERVER, 'the header control is gone'


def test_the_terminal_corrects_its_path_after_the_shell_reads_its_rc():
    """`env=` alone loses to the rc file.

    An interactive shell inherits the environment and *then* runs `.zshrc`, where
    `eval "$(pyenv init -)"` prepends its shims over the project venv. Measured: with leela's
    env set correctly, `python` still resolved to ~/.pyenv/shims/python. The same prepend is
    typed into the shell once it is up, where nothing re-orders it.
    """
    assert 'prelude' in SERVER, 'the pty takes one'
    assert 'os.write(master, self.prelude.encode()' in SERVER, 'written after the shell starts'
    assert 'export PATH=' in SERVER and '$PATH' in SERVER


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
    """Order matters: activating selects the new root's node, which must exist by then.

    Redrawing after, or not at all, left the folder open on the server and absent from the
    panel until a browser reload.
    """
    block = JS[JS.index('async function addRoot'):]
    block = block[:block.index('\ndocument.addEventListener')]
    body = block[block.index('const open = async path =>'):block.index('input.oninput = draw')]
    assert "await post('/fs/add-root'" in body
    assert body.index('refreshFileTree(target)') < body.index('activateRoot(target)'), \
        'the tree is rebuilt before the new root is selected in it'


def test_the_interpreter_and_a_new_venv_follow_the_chosen_folder(tmp_path):
    """With two folders open, the picker described the first one and created into it.

    Worse than a stale panel: `/runtime/create` put the second project's environment inside
    the first project's directory, which is hard to notice and annoying to undo. Both routes
    now use `project_root`, so the picker, the release pipeline and the terminals agree about
    which project they are in.
    """
    a, b = tmp_path/'first', tmp_path/'second'
    for d in (a, b): (d/'src').mkdir(parents=True)
    py = a/'.venv'/'bin'/'python'                     # only the first folder has an environment
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
    """`export FOO=bar` is not fish, and fish has no `export` at all.

    The prelude is *typed into* the shell rather than set in its environment, because an rc file
    running `pyenv init -` afterwards would otherwise prepend its shims over the project venv. So
    it has to be a command that shell understands -- under fish every terminal opened with
    `fish: Unknown command: export` printed over the first prompt.
    """
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
    """The browser picks terminal ids, so it has to know which are taken.

    A pty outlives its websocket on purpose, so that reloading the page can reattach. But the
    client's counter restarts at zero on reload, and `Pty.state` did not say what key anything
    was under -- so `term-1` was handed out again, `open` returned the *existing* pty, and a new
    terminal came up holding an old session's scrollback and its running process.
    """
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


def test_the_shell_is_a_login_shell_unless_told_otherwise():
    """`-l` is what makes an IDE terminal behave like the one in the dock.

    On macOS PATH and tool setup live in login configuration, so a terminal that skips it is the
    one where `uv` is mysteriously missing. Explicit arguments replace the flag rather than adding
    to it: someone who spelled the arguments out has said what they want.
    """
    from leela.blocks.term.term import default_shell, shell_argv
    assert shell_argv('/opt/homebrew/bin/fish') == ['/opt/homebrew/bin/fish', '-l']
    assert shell_argv('/bin/bash', login=False) == ['/bin/bash']
    assert shell_argv('/bin/bash', ['-i', '-c', 'true']) == ['/bin/bash', '-i', '-c', 'true']
    assert shell_argv('', (), True) == [default_shell(), '-l'], 'empty means $SHELL'


def test_an_external_terminal_is_offered_only_when_one_is_installed(tmp_path, monkeypatch):
    """xterm.js cannot be attached to a running terminal, so the honest offer is to launch one.

    A configured command wins, `{dir}` is where the project goes, and a template that forgot to
    say gets it appended -- otherwise the button would silently open someone's home directory.
    """
    from leela.blocks.term import term as T
    assert T.external_terminal_argv(tmp_path, 'kaku {dir}') == ['kaku', str(tmp_path)]
    assert T.external_terminal_argv(tmp_path, 'kaku') == ['kaku', str(tmp_path)]
    assert T.external_terminal_argv(tmp_path, 'wezterm start --cwd {dir}') == \
        ['wezterm', 'start', '--cwd', str(tmp_path)]

    # Nothing configured and nothing installed: the button must be absent, not broken.
    monkeypatch.setattr(T.shutil, 'which', lambda n: None)
    monkeypatch.setattr(T, 'EXTERNAL_TERMINALS', (('NoSuchTerminal', 'no-such-terminal'),))
    assert T.external_terminal_argv(tmp_path) is None, 'no terminal, no button'


def test_the_external_terminal_button_is_offered_only_when_one_exists():
    """Hidden until the server says it found a terminal, so it never fails when pressed.

    The honest framing matters here: this hands the project to a real terminal rather than
    pretending the embedded one is it, because an already-running emulator owns its own pty and a
    browser pane cannot adopt its window.
    """
    assert "id='termexternal'" in SERVER and 'leeExternalTerm()' in SERVER
    block = JS[JS.index('async function leeExternalTerm'):JS.index('function leeNewTerm')]
    assert "post('/term/external')" in block
    open_block = JS[JS.index('async function openTerm'):JS.index('async function openReleaseTerm')]
    assert "external.hidden = !(d.external || []).length" in open_block


def test_opening_a_terminal_really_builds_its_argv_from_the_settings(tmp_path):
    """Actually open the pty, because nothing else here does.

    The regression this exists for was a missing import: `shell_argv` was used in the websocket
    handler and never imported, so every terminal failed with `NameError` -- and the whole suite
    stayed green, because the terminal was only ever asserted about as *source text*. The handler
    reports a failed setup as an error frame rather than a traceback, which is exactly what makes
    this checkable: connect, say hello, and require that the first frame is not that.

    `/bin/echo` as the shell keeps it deterministic: it prints its arguments and exits, so the
    bytes coming back prove the argv was assembled from the settings and handed to a real pty.
    """
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
