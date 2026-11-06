"""Which folders the app opens when nobody tells it ,  the whole of a double-click."""

from __future__ import annotations

import json
import os

import pytest
from starlette.testclient import TestClient

import leela_app
from leela.app import ide_app
from leela.core import projects
from leela.workspace import Workspace

@pytest.fixture(autouse=True)
def session_file(tmp_path, monkeypatch):
    "Point the remembered session at a scratch file; it is real state in a real config dir."
    monkeypatch.setattr(projects, 'SESSION', tmp_path/'desktop.json')
    return tmp_path/'desktop.json'

@pytest.fixture(autouse=True)
def serving_file(tmp_path, monkeypatch):
    "And the address a running workspace publishes, for the same reason."
    monkeypatch.setattr(projects, 'SERVING', tmp_path/'serving.json')
    return tmp_path/'serving.json'

@pytest.fixture
def dirs(tmp_path):
    made = []
    for name in ('alpha', 'beta', 'gamma'):
        (tmp_path/name).mkdir()
        made.append(str(tmp_path/name))
    return made


def test_folders_opened_at_once_do_not_overwrite_each_other(tmp_path, session_file):
    "Two request threads, each writing the whole file. A session that will not parse reads as none."
    import threading
    many = []
    for i in range(24):
        (tmp_path/f'p{i}').mkdir()
        many.append(str(tmp_path/f'p{i}'))
    threads = [threading.Thread(target=projects.note_folder, args=(p,)) for p in many]
    for t in threads: t.start()
    for t in threads: t.join()
    assert sorted(projects.last_folders()) == sorted(many), 'every folder survived the others'
    assert json.loads(session_file.read_text()), 'and the file it left is whole'


def test_a_folder_that_has_gone_is_dropped_rather_than_offered(dirs, tmp_path):
    "Projects get deleted, renamed and unmounted between launches."
    projects.remember(dirs[:2])
    os.rmdir(dirs[0])
    assert projects.last_folders() == [dirs[1]]
    assert dirs[0] not in projects.recent_folders()


def test_opening_a_folder_in_the_app_is_remembered_for_next_launch(tmp_path, dirs, monkeypatch):
    "The set that reopens has to follow the workspace, not the arguments it started with."
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'v.db'))
    ws = Workspace(roots=[dirs[0]], port=8000)
    with TestClient(ide_app(ws)) as c:
        c.post('/fs/add_root?path=' + dirs[1], headers={'origin': 'http://testserver', 'sec-fetch-site': 'same-origin'})
        assert projects.last_folders() == [dirs[1]]
        c.post('/fs/remove-root', json={'path': dirs[1]})
    assert projects.last_folders() == []
    assert dirs[1] in projects.recent_folders()

def test_a_folder_handed_to_a_running_app_gets_a_window_of_its_own(tmp_path, dirs, monkeypatch):
    """The Dock-drop path: macOS delivers the folder to the process already running."""
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'v.db'))
    import socket, threading

    import uvicorn
    from leela import desktop
    from leela.hub import WorkspaceHub, WorkspaceSite
    ws = Workspace(roots=[dirs[0]], port=8000)
    projects.note_folder(dirs[0])
    built, opened = [], []
    def build(root, slug):
        built.append(str(root))
        return WorkspaceSite(slug, os.path.basename(str(root)), str(root),
                             ide_app(Workspace(roots=[root])))
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
    hub = WorkspaceHub([WorkspaceSite('alpha', 'alpha', str(dirs[0]), ide_app(ws))], port,
                       build=build)
    monkeypatch.setattr(desktop, 'open_window',
                        lambda url, title='leela', key=None, **kw: opened.append((url, key)))
    server = uvicorn.Server(uvicorn.Config(hub, host='127.0.0.1', port=port, log_level='error'))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    from leela.desktop import wait_for_http
    assert wait_for_http(f'http://127.0.0.1:{port}/', timeout=30)
    try:
        leela_app.open_folder(port, dirs[1])
        assert built == [dirs[1]], 'the folder got a workspace of its own'
        assert [str(r) for r in ws.fs.roots] == [dirs[0]], 'and was not added to the one already open'
        slug = hub.site_at(dirs[1]).slug
        assert opened == [(f'http://127.0.0.1:{hub.ports[slug]}/', slug)] and hub.ports[slug] != port, 'and a window was pointed at its own port'
        assert dirs[1] in projects.last_folders() and dirs[0] in projects.last_folders(), \
            'both are open now: the open set is a union, not a replacement'
        leela_app.open_folder(port, dirs[1])
        assert built == [dirs[1]], 'opening it again builds nothing'
        assert len(opened) == 2 and opened[-1] == opened[0], 'and raises the window it already has'
    finally:
        server.should_exit = True
        thread.join(timeout=3)


def test_a_file_opens_in_its_checkout_else_its_folder_and_never_in_home(tmp_path):
    base = tmp_path.resolve()
    home = base/'home'
    (src := home/'code'/'repo'/'src').mkdir(parents=True); (src.parent/'.git').mkdir()
    (notes := home/'notes').mkdir(); (loose := home/'x.md').write_text('')
    assert projects.workspace_for(src/'a.py', home) == src.parent, 'its checkout'
    assert projects.workspace_for(notes/'n.md', home) == notes, 'no marker: its own folder'
    assert projects.workspace_for(loose, home) is None, 'directly in home: no workspace'
    (home/'.git').mkdir()
    assert projects.workspace_for(notes/'n.md', home) == notes, 'a dotfiles repo makes home a checkout, which is never a workspace'
    assert projects.workspace_for(loose, home) is None
    assert projects.workspace_for('/x.md', home) is None, 'nor is the root'


def test_a_windowed_launch_gets_the_path_a_terminal_has(monkeypatch):
    """Finder and the Dock start an app with almost nothing on PATH, so `git` and `claude` went missing and the app reported no repository and no Claude Code while both worked in its own terminal."""
    import os, shutil
    from leela import use_login_path
    monkeypatch.setenv('PATH', '/usr/bin:/bin')
    got = use_login_path()
    assert len(got.split(os.pathsep)) > 2, 'a stripped PATH must be widened'
    assert shutil.which('git'), 'git is what the git panel needs to find'


def test_an_ascii_locale_is_repaired_before_anything_imports(monkeypatch):
    """The failure it prevents is `UnicodeDecodeError` out of an import, blamed on the import."""
    import locale, sys
    from leela import use_utf8
    if sys.flags.utf8_mode: pytest.skip('UTF-8 mode leaves no ASCII locale to repair')
    was = locale.setlocale(locale.LC_CTYPE)
    try:
        locale.setlocale(locale.LC_CTYPE, 'C')
        assert 'utf-8' not in locale.getpreferredencoding(False).lower(), 'C should be ASCII'
        assert use_utf8() is True
        assert 'utf-8' in locale.getpreferredencoding(False).lower()
    finally: locale.setlocale(locale.LC_CTYPE, was)


def test_a_launch_with_no_arguments_reopens_one_folder(tmp_path, monkeypatch):
    """Quitting with four open and launching again reopened all four, one window each."""
    import leela.core.projects as projects
    monkeypatch.setattr(projects, 'SESSION', tmp_path/'session.json')
    dirs = []
    for n in 'abcd':
        d = tmp_path/n; d.mkdir(); dirs.append(str(d))
    projects.remember(dirs)
    assert len(projects.last_folders()) == 4, 'the open set still records what was open'
    assert projects.last_folder() == [dirs[-1]], 'a launch opens the last of them and no more'
    # `note_folder` appends, so opening another makes it the one a relaunch comes back to.
    later = tmp_path/'e'; later.mkdir()
    projects.note_folder(str(later))
    assert projects.last_folder() == [str(later)]
    # An already-open folder keeps its place in the open set; only `recent` fronts it.
    projects.note_folder(dirs[0])
    assert projects.last_folder() == [str(later)]
    assert projects.recent_folders()[0] == dirs[0], 'recent is the recency list'


def test_a_folder_under_the_system_temp_dir_is_never_remembered(tmp_path, monkeypatch):
    """A folder in the temp dir belongs to a test, a probe or an unpacked archive."""
    import tempfile
    from pathlib import Path
    from leela.core import projects
    from leela.workspace import Workspace
    # pytest's own `tmp_path` is under the real temp dir, so the temp dir is narrowed to a subtree
    # of it here. Otherwise there is no folder in this test the guard would keep.
    scratch_root = tmp_path/'scratch'; scratch_root.mkdir()
    monkeypatch.setattr(tempfile, 'gettempdir', lambda: str(scratch_root))
    desktop = tmp_path/'desktop.json'
    monkeypatch.setattr(projects, 'SESSION', desktop)
    monkeypatch.setattr(projects, 'DEFAULT_SESSION', desktop)   # the guarded one, for this test
    scratch = scratch_root/'tmpabcd'; scratch.mkdir()
    real = tmp_path/'project'; real.mkdir()
    assert projects._temporary(scratch) and not projects._temporary(real)
    projects.note_folder(str(scratch)); projects.note_folder(str(real))
    assert [Path(f).name for f in projects.session()['folders']] == [real.name]
    assert not any(projects._temporary(Path(f)) for f in projects.session()['recent'])

    state = tmp_path/'workspace.json'
    monkeypatch.setattr('leela.workspace.ws_path', lambda: state)
    Workspace(roots=[real]).save(state)
    Workspace(roots=[scratch]).save(state)
    assert [Path(r).name for r in state.read_json()['roots']] == [real.name], \
        'and the saved session never carries one either, however it got in'

