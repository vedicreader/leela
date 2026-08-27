"""Which folders the app opens when nobody tells it — the whole of a double-click.

A command line answers "which project" every time. A desktop app is launched by double-click,
by a Dock drop, or by Finder's "Open With", and has to work all three out for itself. These
tests are about that: what is remembered, what is offered, and -- the one with teeth -- what is
*not* opened when there is nothing to go on.
"""

from __future__ import annotations

import json
import os
import sys

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

def test_nothing_remembered_reads_as_nothing_rather_than_failing(session_file):
    assert projects.session() == {'folders': [], 'recent': []}
    assert projects.last_folders() == [] and projects.recent_folders() == []

def test_a_corrupt_session_file_does_not_stop_the_app_opening(session_file):
    "Half a write survives a crash; refusing to launch over it would not be an improvement."
    session_file.write_text('{"folders": [')
    assert projects.last_folders() == []

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

def test_the_folders_a_launch_opened_are_what_the_next_one_reopens(dirs):
    projects.remember(dirs[:2])
    assert projects.last_folders() == dirs[:2]

def test_opening_another_folder_adds_to_the_set_rather_than_replacing_it(dirs):
    """Under `--app` each folder is its own `Workspace`.

    Each recording itself would leave the session naming whichever one wrote last.
    """
    projects.remember([dirs[0]])
    projects.note_folder(dirs[1])
    assert projects.last_folders() == dirs[:2]

def test_closing_a_folder_stops_it_reopening_but_does_not_forget_it(dirs):
    projects.remember(dirs[:2])
    projects.drop_folder(dirs[0])
    assert projects.last_folders() == [dirs[1]]
    assert dirs[0] in projects.recent_folders(), 'closing a project is not forgetting it'

def test_recent_projects_come_back_most_recently_opened_first(dirs):
    for d in dirs: projects.note_folder(d)
    assert projects.recent_folders()[:3] == list(reversed(dirs))

def test_the_recent_list_is_bounded(tmp_path):
    for i in range(projects.MAX_RECENT + 8):
        d = tmp_path/f'p{i}'; d.mkdir()
        projects.note_folder(str(d))
    assert len(projects.recent_folders()) == projects.MAX_RECENT

def test_a_folder_that_has_gone_is_dropped_rather_than_offered(dirs, tmp_path):
    "Projects get deleted, renamed and unmounted between launches."
    projects.remember(dirs[:2])
    os.rmdir(dirs[0])
    assert projects.last_folders() == [dirs[1]]
    assert dirs[0] not in projects.recent_folders()

def test_forgetting_a_project_removes_it_from_the_welcome_screen(dirs):
    for d in dirs: projects.note_folder(d)
    projects.forget_recent(dirs[1])
    assert dirs[1] not in projects.recent_folders()

def test_the_same_folder_is_only_listed_once(dirs):
    projects.note_folder(dirs[0])
    projects.note_folder(dirs[0] + '/')
    projects.note_folder(dirs[0])
    assert projects.recent_folders().count(dirs[0]) == 1

def test_a_launch_with_no_arguments_reopens_the_last_session(dirs, monkeypatch):
    "One window, not one per folder remembered. See `last_folder`."
    projects.remember(dirs[:2])
    seen = {}
    monkeypatch.setattr(leela_app, 'serve', lambda args, background=False: seen.setdefault('args', args))
    monkeypatch.setattr(leela_app, 'free_port', lambda preferred=5001: 5199)
    monkeypatch.setattr('leela.desktop.shell_ready', lambda *a: (True, 'gtk'))
    monkeypatch.setattr('leela.desktop.start_cdp', lambda *a, **k: None)
    monkeypatch.setattr('leela.desktop.run_shell', lambda urls, **kw: seen.update(urls=urls, **kw))
    monkeypatch.setattr(leela_app.sys, 'argv', ['leela_app.py'])
    leela_app.run()
    assert seen['args'][-1:] == [dirs[1]], 'the most recently opened, and only it'

def test_a_folder_given_by_the_desktop_wins_over_the_remembered_session(dirs, monkeypatch):
    "Opening a project with Leela means that project, not the one from yesterday."
    projects.remember([dirs[0]])
    seen = {}
    monkeypatch.setattr(leela_app, 'serve', lambda args, background=False: seen.setdefault('args', args))
    monkeypatch.setattr(leela_app, 'free_port', lambda preferred=5001: 5199)
    monkeypatch.setattr('leela.desktop.shell_ready', lambda *a: (True, 'gtk'))
    monkeypatch.setattr('leela.desktop.start_cdp', lambda *a, **k: None)
    monkeypatch.setattr('leela.desktop.run_shell', lambda urls, **kw: seen.update(urls=urls, **kw))
    monkeypatch.setattr(leela_app.sys, 'argv', ['leela_app.py', dirs[2]])
    leela_app.run()
    assert seen['args'][-1:] == [dirs[2]]
    assert projects.last_folders() == [dirs[2]]

def test_every_workspace_gets_its_own_window(dirs, monkeypatch):
    """`--app` gives each folder an isolated workspace behind a host-dispatching hub.

    One window on the bare loopback host would show the first folder and strand the rest.
    """
    seen = {}
    monkeypatch.setattr(leela_app, 'serve', lambda args, background=False: None)
    monkeypatch.setattr(leela_app, 'free_port', lambda preferred=5001: 5199)
    monkeypatch.setattr('leela.desktop.shell_ready', lambda *a: (True, 'gtk'))
    monkeypatch.setattr('leela.desktop.start_cdp', lambda *a, **k: None)
    monkeypatch.setattr('leela.desktop.run_shell', lambda urls, **kw: seen.update(urls=urls, **kw))
    monkeypatch.setattr(leela_app.sys, 'argv', ['leela_app.py', *dirs[:2]])
    leela_app.run()
    assert seen['urls'] == ['http://alpha.localhost:5199/', 'http://beta.localhost:5199/']
    assert seen['titles'] == ['leela — alpha', 'leela — beta']

def test_with_nothing_to_open_there_is_still_one_window(monkeypatch):
    seen = {}
    monkeypatch.setattr(leela_app, 'serve', lambda args, background=False: None)
    monkeypatch.setattr(leela_app, 'free_port', lambda preferred=5001: 5199)
    monkeypatch.setattr('leela.desktop.shell_ready', lambda *a: (True, 'gtk'))
    monkeypatch.setattr('leela.desktop.start_cdp', lambda *a, **k: None)
    monkeypatch.setattr('leela.desktop.run_shell', lambda urls, **kw: seen.update(urls=urls, **kw))
    monkeypatch.setattr(leela_app.sys, 'argv', ['leela_app.py'])
    leela_app.run()
    assert seen['urls'] == ['http://127.0.0.1:5199/'] and seen['titles'] == ['leela']

def test_a_frozen_app_with_no_folder_opens_on_nothing_rather_than_on_your_home_directory():
    """The bad guess this replaces had teeth.

    `leela` from a shell means "here", and the shell already chose where here is. A
    double-clicked application has no such answer, and the old fallback -- the home directory
    -- handed Kosha every file the user owns to index and the watcher every one to follow.
    """
    import inspect

    from leela import app as appmod
    src = inspect.getsource(appmod.serve_ide)
    assert 'Path.home()' not in src, 'the home-directory fallback is back'
    assert "not getattr(sys, 'frozen', False)" in src

def test_a_workspace_with_no_folders_still_serves(tmp_path, monkeypatch):
    "Opening on nothing has to be a usable screen, not a broken one."
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'v.db'))
    ws = Workspace(roots=[], port=8000)
    with TestClient(ide_app(ws)) as c:
        page = c.get('/')
        assert page.status_code == 200
        assert 'Open a folder' in page.text, 'the welcome screen must offer a way in'
        assert 'leerecent' in page.text
        assert c.get('/fs/recent').json()['ok']

def test_the_welcome_screen_offers_the_projects_you_have_opened_before(tmp_path, dirs, monkeypatch):
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'v.db'))
    for d in dirs: projects.note_folder(d)
    ws = Workspace(roots=[dirs[0]], port=8000)
    with TestClient(ide_app(ws)) as c:
        d = c.get('/fs/recent').json()
    listed = {r['name']: r['open'] for r in d['recent']}
    assert listed == {'alpha': True, 'beta': False, 'gamma': False}
    assert d['home'] == str(__import__('pathlib').Path.home())

def test_opening_a_folder_in_the_app_is_remembered_for_next_launch(tmp_path, dirs, monkeypatch):
    "The set that reopens has to follow the workspace, not the arguments it started with."
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'v.db'))
    ws = Workspace(roots=[dirs[0]], port=8000)
    with TestClient(ide_app(ws)) as c:
        c.get('/fs/add_root?path=' + dirs[1])
        assert projects.last_folders() == [dirs[1]]
        c.post('/fs/remove-root', json={'path': dirs[1]})
    assert projects.last_folders() == []
    assert dirs[1] in projects.recent_folders()

def test_a_folder_handed_to_a_running_app_gets_a_window_of_its_own(tmp_path, dirs, monkeypatch):
    """The Dock-drop path: macOS delivers the folder to the process already running.

    It used to be added as another root of the window already open, so two projects shared one
    kernel, one tab bar and one agent. A folder is a workspace, and a workspace is a window. It
    still goes through HTTP because the server owns the workspaces on another thread and loop.
    """
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'v.db'))
    import threading

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
    hub = WorkspaceHub([WorkspaceSite('alpha', 'alpha', str(dirs[0]), ide_app(ws))], 5207,
                       build=build)
    monkeypatch.setattr(desktop, 'open_window',
                        lambda url, title='leela', key=None, **kw: opened.append((url, key)))
    server = uvicorn.Server(uvicorn.Config(hub, host='127.0.0.1', port=5207, log_level='error'))
    threading.Thread(target=server.run, daemon=True).start()
    from leela.desktop import wait_for_http
    assert wait_for_http('http://127.0.0.1:5207/', timeout=30)
    try:
        leela_app.open_folder(5207, dirs[1])
        assert built == [dirs[1]], 'the folder got a workspace of its own'
        assert [str(r) for r in ws.fs.roots] == [dirs[0]], 'and was not added to the one already open'
        assert opened == [(f'http://{hub.site_at(dirs[1]).slug}.localhost:5207/',
                           hub.site_at(dirs[1]).slug)], 'and a window was pointed at it'
        assert dirs[1] in projects.last_folders() and dirs[0] in projects.last_folders(), \
            'both are open now: the open set is a union, not a replacement'
        leela_app.open_folder(5207, dirs[1])
        assert built == [dirs[1]], 'opening it again builds nothing'
        assert len(opened) == 2 and opened[-1] == opened[0], 'and raises the window it already has'
    finally: server.should_exit = True

def test_a_folder_opened_as_its_own_site_is_remembered_whoever_opened_it(dirs):
    """The browser posts `/hub/open` and gets no desktop shell, so the shell cannot be what remembers.

    Noting it there left a folder opened from a browser tab out of the reopen set and out of the
    welcome screen's recent list, while the same folder opened from the app was in both.
    """
    from leela.hub import WorkspaceHub, WorkspaceSite
    build = lambda root, slug: WorkspaceSite(slug, os.path.basename(str(root)), str(root), lambda *a: None)
    hub = WorkspaceHub([WorkspaceSite('alpha', 'alpha', dirs[0], lambda *a: None)], 5209, build=build)
    hub.open_folder(dirs[1])
    assert dirs[1] in projects.last_folders(), 'the hub is the seam both legs pass through'
    assert projects.recent_folders()[0] == dirs[1]
    projects.note_folder(dirs[0])
    hub.open_folder(dirs[1])                       # already a site: reused, and raised to the top
    assert projects.recent_folders()[0] == dirs[1]


def test_a_folder_that_has_gone_is_refused_and_opens_no_window(tmp_path, dirs, monkeypatch):
    "An empty window naming a folder that is not there is worse than a line saying why."
    import threading

    import uvicorn
    from leela import desktop
    from leela.hub import WorkspaceHub, WorkspaceSite
    opened = []
    hub = WorkspaceHub([WorkspaceSite('alpha', 'alpha', str(dirs[0]), lambda *a: None)], 5208,
                       build=lambda root, slug: pytest.fail('nothing may be built for a non-folder'))
    monkeypatch.setattr(desktop, 'open_window', lambda *a, **kw: opened.append(a))
    server = uvicorn.Server(uvicorn.Config(hub, host='127.0.0.1', port=5208, log_level='error'))
    threading.Thread(target=server.run, daemon=True).start()
    from leela.desktop import wait_for_http
    assert wait_for_http('http://127.0.0.1:5208/', timeout=30)
    try:
        assert leela_app.open_folder(5208, tmp_path/'never-existed') is None
        assert opened == [], 'no window is left showing nothing'
    finally: server.should_exit = True

@pytest.mark.skipif(sys.platform == 'darwin', reason='macOS really does register the handler')
def test_the_open_folder_handler_is_a_no_op_where_there_is_nothing_to_register():
    "Windows and Linux get their folders through argv; asking for a handler must not raise."
    from leela.desktop import watch_open_events
    assert watch_open_events(lambda p: None) is None

def test_a_running_workspace_publishes_where_it_is_answering(serving_file, dirs):
    """A hotkey, a script, anything outside the window has to find it, and the desktop shell takes
    whatever port is free -- so there is nothing to guess at."""
    d = projects.now_serving('127.0.0.1', 5173, dirs)
    assert d['url'] == 'http://127.0.0.1:5173/' and d['pid'] == os.getpid()
    assert d['folders'] == dirs
    live = projects.serving()
    assert live['port'] == 5173 and live['url'] == d['url']
    projects.served()
    assert projects.serving() is None, 'and it stops claiming to be up once it is not'

def test_an_address_left_behind_by_a_dead_workspace_is_not_offered(serving_file):
    """A workspace killed outright never reaches its own cleanup. By the time anything reads the
    file the port may belong to something else, which is the one way this could misdirect a post."""
    projects.now_serving('127.0.0.1', 5173, [])
    d = json.loads(serving_file.read_text()); d['pid'] = 2 ** 31 - 1
    serving_file.write_text(json.dumps(d))
    assert projects.serving() is None

def test_a_missing_or_unreadable_address_reads_as_nothing_rather_than_failing(serving_file):
    assert projects.serving() is None
    serving_file.write_text('{not json')
    assert projects.serving() is None
    serving_file.write_text('{"pid": 1}')
    assert projects.serving() is None, 'an entry with no port names nowhere'
    projects.served(), projects.served()          # removing one that is already gone is not an error


def test_a_windowed_launch_gets_the_path_a_terminal_has(monkeypatch):
    """Finder and the Dock start an app with almost nothing on PATH, so `git` and `claude` went
    missing and the app reported no repository and no Claude Code while both worked in its own
    terminal. Asking the login shell is what closes that gap."""
    import os, shutil
    from leela import use_login_path
    monkeypatch.setenv('PATH', '/usr/bin:/bin')
    got = use_login_path()
    assert len(got.split(os.pathsep)) > 2, 'a stripped PATH must be widened'
    assert shutil.which('git'), 'git is what the git panel needs to find'

def test_the_tool_directories_are_added_when_the_shell_cannot_be_asked(monkeypatch, tmp_path):
    "No SHELL, or one that fails, still has to leave the usual places on PATH."
    import os
    import leela
    monkeypatch.delenv('SHELL', raising=False)
    monkeypatch.setenv('PATH', '/usr/bin')
    real = tmp_path/'bin'; real.mkdir()
    monkeypatch.setattr(leela, 'TOOL_DIRS', (str(real), '/definitely/not/here'))
    got = leela.use_login_path().split(os.pathsep)
    assert leela.login_path() is None, 'with no SHELL there is nothing to ask'
    assert str(real) in got and '/definitely/not/here' not in got, 'only directories that exist'

def test_asking_the_shell_never_hangs_the_launch(monkeypatch):
    "A profile that blocks would otherwise stall every windowed start before the window appears."
    import subprocess
    import leela
    def slow(*a, **kw): raise subprocess.TimeoutExpired(cmd='sh', timeout=3)
    monkeypatch.setattr(leela.__dict__['subprocess'] if 'subprocess' in leela.__dict__ else subprocess,
                        'run', slow, raising=False)
    monkeypatch.setattr(subprocess, 'run', slow)
    monkeypatch.setenv('SHELL', '/bin/zsh')
    assert leela.login_path() is None


def test_an_ascii_locale_is_repaired_before_anything_imports(monkeypatch):
    "The failure it prevents is `UnicodeDecodeError` out of an import, blamed on the import."
    import locale
    from leela import use_utf8
    was = locale.setlocale(locale.LC_CTYPE)
    try:
        locale.setlocale(locale.LC_CTYPE, 'C')
        assert 'utf-8' not in locale.getpreferredencoding(False).lower(), 'C should be ASCII'
        assert use_utf8() is True
        assert 'utf-8' in locale.getpreferredencoding(False).lower()
    finally: locale.setlocale(locale.LC_CTYPE, was)

def test_a_locale_that_is_already_utf8_is_left_alone(monkeypatch):
    "Nothing to fix means no `setlocale` call, so a deliberate locale is not overwritten."
    import locale
    import leela
    monkeypatch.setattr(leela, 'UTF8_LOCALES', ())
    assert leela.use_utf8() is ('utf-8' in locale.getpreferredencoding(False).lower())


def test_a_launch_with_no_arguments_reopens_one_folder(tmp_path, monkeypatch):
    """Quitting with four open and launching again reopened all four, one window each. The rest are
    still in `recent`, which the Dock menu and the welcome screen offer."""
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

def test_with_nothing_remembered_a_launch_opens_no_folder(tmp_path, monkeypatch):
    "A first run has no history, and the welcome screen is the right answer, not a guess."
    import leela.core.projects as projects
    monkeypatch.setattr(projects, 'SESSION', tmp_path/'empty.json')
    assert projects.last_folder() == []

def test_a_folder_under_the_system_temp_dir_is_never_remembered(tmp_path, monkeypatch):
    """A folder in the temp dir belongs to a test, a probe or an unpacked archive. One written into
    the session a person opens is a folder they then have to close by hand, in every window, and a
    suite that opened eleven of them put all eleven in front of somebody."""
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

def test_a_test_naming_its_own_session_file_keeps_what_it_puts_there(tmp_path, monkeypatch):
    "The guard is about the session a person opens. Anything else is the caller's own file."
    from leela.core import projects
    monkeypatch.setattr(projects, 'SESSION', tmp_path/'desktop.json')
    projects.note_folder(str(tmp_path))          # pytest's own tmp_path is under the temp dir
    assert projects.session()['folders'] == [str(tmp_path.resolve())]
