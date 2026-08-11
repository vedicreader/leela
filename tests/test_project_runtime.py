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
from tests.assets import JS


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
