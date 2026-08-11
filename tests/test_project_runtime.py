"""Opening a folder with no environment gets one, rather than falling back to PATH.

The failure this prevents is quiet: `project_python` returns None, `pool.default_python` stays
None, and the kernel launches under whatever `python3` resolves to on PATH -- often a system
3.8 with none of the project's dependencies. Nothing errors; the notebook just runs somewhere
nobody chose.
"""

import shutil

import pytest
from starlette.testclient import TestClient

from leela.app import ide_app
from leela.blocks.runtime.kernels import project_python
from leela.workspace import Workspace
from tests.assets import CSS, JS


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
    assert 'setTimeout(() => search(q), 200)' in block, 'debounced, not per keystroke'
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
